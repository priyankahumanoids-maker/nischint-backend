"""Canonical Trial/Paid/Grace/Lifeline authority for Family Circle Phase 6.

Provider neutral: no live gateway is called here. Only an already-verified provider
adapter may construct ``VerifiedBillingEvent`` and hand it to this service.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_circle_permissions import (
    ENTITLEMENT_ACTIVE,
    ENTITLEMENT_GRACE,
    ENTITLEMENT_LIFELINE,
    PLAN_FAMILY,
    PLAN_INDIVIDUAL,
    PLAN_TRIAL,
)
from app.models.family_circle import FamilyCircle
from app.services.family_circle_audit_service import append_family_audit
from app.services.family_circle_billing_contract import VerifiedBillingEvent

GRACE_DAYS = 3


@dataclass(frozen=True)
class EntitlementSnapshot:
    state: str
    permission_entitlement: str
    reason: str
    access_until: datetime | None = None
    grace_until: datetime | None = None
    payment_required: bool = False
    cancel_at_period_end: bool = False
    pending_plan: str | None = None

    @property
    def lifeline(self) -> bool:
        return self.permission_entitlement == ENTITLEMENT_LIFELINE


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def seed_entitlement_state(session: AsyncSession, circle: FamilyCircle, *, now: datetime | None = None) -> None:
    point = _utc(now) or datetime.now(timezone.utc)
    if circle.plan == PLAN_TRIAL:
        state = "trial_active"
        period_end = circle.trial_ends_at
    elif circle.plan in {PLAN_INDIVIDUAL, PLAN_FAMILY}:
        # Selecting a paid plan never activates it. A future verified provider
        # event is the only route into paid_active.
        state = "payment_pending"
        period_end = None
    else:
        return
    await session.execute(
        text(
            """
            INSERT INTO family_circle_entitlements
                (circle_id, state, current_period_end, updated_at)
            VALUES (:circle_id, :state, :period_end, :updated_at)
            ON CONFLICT (circle_id) DO NOTHING
            """
        ),
        {"circle_id": circle.id, "state": state, "period_end": period_end, "updated_at": point},
    )


async def _row(session: AsyncSession, circle_id) -> dict | None:
    result = await session.execute(
        text(
            """
            SELECT state, provider, provider_subscription_ref, current_period_start,
                   current_period_end, grace_until, cancel_at_period_end,
                   pending_plan, pending_plan_effective_at, pending_seat_assignments,
                   updated_at
              FROM family_circle_entitlements
             WHERE circle_id = :circle_id
            """
        ),
        {"circle_id": str(circle_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def resolve_entitlement(session: AsyncSession, circle: FamilyCircle, *, now: datetime | None = None) -> EntitlementSnapshot:
    point = _utc(now) or datetime.now(timezone.utc)
    if circle.plan == PLAN_TRIAL:
        end = _utc(circle.trial_ends_at)
        if circle.trial_started_at is not None and end is not None and point < end:
            return EntitlementSnapshot("trial_active", ENTITLEMENT_ACTIVE, "trial_active", access_until=end)
        return EntitlementSnapshot("lifeline", ENTITLEMENT_LIFELINE, "trial_expired", access_until=end, payment_required=True)

    if circle.plan not in {PLAN_INDIVIDUAL, PLAN_FAMILY}:
        return EntitlementSnapshot("lifeline", ENTITLEMENT_LIFELINE, "plan_uninitialized", payment_required=True)

    row = await _row(session, circle.id)
    if not row:
        return EntitlementSnapshot("payment_pending", ENTITLEMENT_LIFELINE, "payment_not_verified", payment_required=True)

    state = str(row.get("state") or "payment_pending")
    period_end = _utc(row.get("current_period_end"))
    grace_until = _utc(row.get("grace_until"))
    cancel_at_period_end = bool(row.get("cancel_at_period_end"))
    pending_plan = row.get("pending_plan")

    if state == "paid_active":
        if period_end is not None and point >= period_end:
            return EntitlementSnapshot(
                "lifeline", ENTITLEMENT_LIFELINE, "paid_period_ended",
                access_until=period_end, payment_required=True,
                cancel_at_period_end=cancel_at_period_end, pending_plan=pending_plan,
            )
        return EntitlementSnapshot(
            "paid_active", ENTITLEMENT_ACTIVE, "paid_active", access_until=period_end,
            cancel_at_period_end=cancel_at_period_end, pending_plan=pending_plan,
        )
    if state == "grace":
        if grace_until is not None and point < grace_until:
            return EntitlementSnapshot(
                "grace", ENTITLEMENT_GRACE, "renewal_grace",
                access_until=period_end, grace_until=grace_until,
                cancel_at_period_end=cancel_at_period_end, pending_plan=pending_plan,
            )
        return EntitlementSnapshot(
            "lifeline", ENTITLEMENT_LIFELINE, "renewal_grace_expired",
            access_until=period_end, grace_until=grace_until, payment_required=True,
            cancel_at_period_end=cancel_at_period_end, pending_plan=pending_plan,
        )
    if state == "lifeline":
        return EntitlementSnapshot(
            "lifeline", ENTITLEMENT_LIFELINE, "billing_inactive",
            access_until=period_end, payment_required=True,
            cancel_at_period_end=cancel_at_period_end, pending_plan=pending_plan,
        )
    return EntitlementSnapshot(
        "payment_pending", ENTITLEMENT_LIFELINE, "payment_not_verified",
        payment_required=True, pending_plan=pending_plan,
    )


def _normalize_json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return value


async def apply_verified_billing_event(
    session: AsyncSession,
    *,
    circle: FamilyCircle,
    event: VerifiedBillingEvent,
) -> EntitlementSnapshot:
    """Apply one provider event that was already cryptographically verified.

    The function is deliberately not a public/app-success endpoint. It is
    idempotent by ``provider + provider_event_id`` and ignores stale distinct
    events whose effective time is older than the last applied transition.
    """
    inserted = await session.execute(
        text(
            """
            INSERT INTO family_billing_events
                (id, circle_id, provider, provider_event_id, event_type, payload_digest, effective_at, created_at)
            VALUES
                (:id, :circle_id, :provider, :provider_event_id, :event_type, :payload_digest, :effective_at, NOW())
            ON CONFLICT (provider, provider_event_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "id": uuid.uuid4(),
            "circle_id": circle.id,
            "provider": event.provider,
            "provider_event_id": event.provider_event_id,
            "event_type": event.event_type,
            "payload_digest": event.payload_digest,
            "effective_at": event.effective_at,
        },
    )
    if inserted.scalar_one_or_none() is None:
        return await resolve_entitlement(session, circle, now=event.effective_at)

    current = await _row(session, circle.id) or {}
    last_updated = _utc(current.get("updated_at"))
    if last_updated is not None and event.effective_at < last_updated:
        await append_family_audit(
            session,
            circle_id=circle.id,
            actor_user_id=None,
            subject_user_id=None,
            event_type="billing_event_ignored_stale",
            details={
                "provider": event.provider,
                "event_type": event.event_type,
                "event_id": event.provider_event_id,
                "effective_at": event.effective_at.isoformat(),
                "last_applied_at": last_updated.isoformat(),
            },
            event_key=f"billing-stale:{event.provider}:{event.provider_event_id}",
        )
        return await resolve_entitlement(session, circle, now=event.effective_at)

    state = str(current.get("state") or ("trial_active" if circle.plan == PLAN_TRIAL else "payment_pending"))
    period_end = _utc(current.get("current_period_end"))
    grace_until = _utc(current.get("grace_until"))
    cancel_at_period_end = bool(current.get("cancel_at_period_end"))
    pending_plan = current.get("pending_plan")
    pending_effective = _utc(current.get("pending_plan_effective_at"))
    pending_seat_assignments = _normalize_json(current.get("pending_seat_assignments"))

    if event.event_type == "payment_activated":
        if event.target_plan not in {PLAN_INDIVIDUAL, PLAN_FAMILY}:
            raise ValueError("Verified activation requires an Individual or Family target plan.")
        if event.current_period_end is None:
            raise ValueError("Verified paid activation requires current_period_end.")
        if event.target_plan == PLAN_FAMILY:
            from app.services.family_circle_plan_change_service import apply_upgrade_to_family
            await apply_upgrade_to_family(session, circle=circle, effective_at=event.effective_at)
        else:
            circle.plan = PLAN_INDIVIDUAL
        state = "paid_active"
        period_end = event.current_period_end
        grace_until = None
        cancel_at_period_end = False
        pending_plan = None
        pending_effective = None
        pending_seat_assignments = None

    elif event.event_type == "renewal_succeeded":
        if circle.plan not in {PLAN_INDIVIDUAL, PLAN_FAMILY} or event.current_period_end is None:
            raise ValueError("Verified renewal requires an active paid plan and current_period_end.")
        state = "paid_active"
        period_end = event.current_period_end
        grace_until = None
        # Preserve cancel/pending downgrade state. A renewal event is not an
        # instruction to discard a scheduled end-of-period change.

    elif event.event_type == "upgrade_succeeded":
        if event.target_plan not in {PLAN_INDIVIDUAL, PLAN_FAMILY} or event.current_period_end is None:
            raise ValueError("Verified upgrade requires a paid target plan and current_period_end.")
        if event.target_plan == PLAN_FAMILY:
            from app.services.family_circle_plan_change_service import apply_upgrade_to_family
            await apply_upgrade_to_family(session, circle=circle, effective_at=event.effective_at)
        else:
            circle.plan = PLAN_INDIVIDUAL
        state = "paid_active"
        period_end = event.current_period_end
        grace_until = None
        pending_plan = None
        pending_effective = None
        pending_seat_assignments = None

    elif event.event_type == "renewal_failed":
        if circle.plan not in {PLAN_INDIVIDUAL, PLAN_FAMILY}:
            raise ValueError("Renewal failure is only valid for a paid plan.")
        state = "grace"
        grace_until = event.effective_at + timedelta(days=GRACE_DAYS)
        if event.current_period_end is not None:
            period_end = event.current_period_end

    elif event.event_type == "cancel_scheduled":
        # Cancellation changes only end-of-period intent. It must not destroy a
        # live grace window or a pending downgrade selection.
        cancel_at_period_end = True
        if event.current_period_end is not None:
            period_end = event.current_period_end

    elif event.event_type == "downgrade_scheduled":
        if event.target_plan != PLAN_INDIVIDUAL:
            raise ValueError("Only Family to Individual downgrade is supported.")
        if not pending_seat_assignments:
            raise ValueError("Family downgrade requires Owner seat selection before provider scheduling.")
        pending_plan = PLAN_INDIVIDUAL
        pending_effective = event.current_period_end or period_end
        if pending_effective is None:
            raise ValueError("Downgrade schedule requires a billing-period end.")
        if event.current_period_end is not None:
            period_end = event.current_period_end

    elif event.event_type == "downgrade_effective":
        if event.target_plan != PLAN_INDIVIDUAL or event.current_period_end is None:
            raise ValueError("Verified downgrade effective event requires Individual target and new period end.")
        from app.services.family_circle_plan_change_service import apply_staged_family_to_individual_downgrade
        await apply_staged_family_to_individual_downgrade(session, circle=circle, effective_at=event.effective_at)
        state = "paid_active"
        period_end = event.current_period_end
        grace_until = None
        cancel_at_period_end = False
        pending_plan = None
        pending_effective = None
        pending_seat_assignments = None

    elif event.event_type == "period_ended":
        state = "lifeline"
        grace_until = None
        cancel_at_period_end = False

    await session.execute(
        text(
            """
            INSERT INTO family_circle_entitlements
                (circle_id, state, provider, current_period_end, grace_until,
                 cancel_at_period_end, pending_plan, pending_plan_effective_at,
                 pending_seat_assignments, updated_at)
            VALUES
                (:circle_id, :state, :provider, :period_end, :grace_until,
                 :cancel_at_period_end, :pending_plan, :pending_effective_at,
                 CAST(:pending_seat_assignments AS JSONB), :updated_at)
            ON CONFLICT (circle_id) DO UPDATE SET
                state=EXCLUDED.state,
                provider=EXCLUDED.provider,
                current_period_end=EXCLUDED.current_period_end,
                grace_until=EXCLUDED.grace_until,
                cancel_at_period_end=EXCLUDED.cancel_at_period_end,
                pending_plan=EXCLUDED.pending_plan,
                pending_plan_effective_at=EXCLUDED.pending_plan_effective_at,
                pending_seat_assignments=EXCLUDED.pending_seat_assignments,
                updated_at=EXCLUDED.updated_at
            """
        ),
        {
            "circle_id": circle.id,
            "state": state,
            "provider": event.provider,
            "period_end": period_end,
            "grace_until": grace_until,
            "cancel_at_period_end": cancel_at_period_end,
            "pending_plan": pending_plan,
            "pending_effective_at": pending_effective,
            "pending_seat_assignments": json.dumps(pending_seat_assignments) if pending_seat_assignments is not None else None,
            "updated_at": event.effective_at,
        },
    )
    await append_family_audit(
        session,
        circle_id=circle.id,
        actor_user_id=None,
        subject_user_id=None,
        event_type="billing_event",
        details={
            "provider": event.provider,
            "event_type": event.event_type,
            "provider_event_id": event.provider_event_id,
            "target_plan": event.target_plan,
        },
        event_key=f"billing:{event.provider}:{event.provider_event_id}",
    )
    return await resolve_entitlement(session, circle, now=event.effective_at)


__all__ = [
    "GRACE_DAYS", "EntitlementSnapshot", "seed_entitlement_state",
    "resolve_entitlement", "apply_verified_billing_event",
]

"""NISCHINT per-protected-member subscription and entitlement authority.

Day 6/7 scope only: no payment gateway. A subscription belongs to the Primary
Guardian and can protect exactly one protected member. Unassigned ACTIVE rows
represent paid/test slots that may generate/re-generate a QR/code until one
protected member successfully joins. QR close/cancel/expiry never consumes a
slot; successful protected-member join does.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.product_roles import is_primary_guardian, is_protected_member, normalize_role
from app.models.user import User

PLAN_PRICES = {"standard": 299, "premium": 499}
VALID_STATUSES = {"pending", "active", "expired", "cancelled"}

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS member_subscriptions (
        id UUID PRIMARY KEY,
        guardian_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        protected_member_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
        plan VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        price_monthly INTEGER NOT NULL,
        starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NULL,
        cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_member_subscriptions_guardian ON member_subscriptions (guardian_user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_member_subscriptions_member ON member_subscriptions (protected_member_user_id)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_member_subscriptions_assigned_live
    ON member_subscriptions (protected_member_user_id)
    WHERE protected_member_user_id IS NOT NULL AND status IN ('active', 'pending')
    """,
    """
    CREATE TABLE IF NOT EXISTS subscription_invite_reservations (
        guardian_user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        subscription_id UUID NULL REFERENCES member_subscriptions(id) ON DELETE CASCADE,
        invite_code VARCHAR(6) NOT NULL UNIQUE,
        purpose VARCHAR(30) NOT NULL DEFAULT 'protected_member',
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_subscription_invite_code ON subscription_invite_reservations (invite_code)",
]

_table_ready = False
_table_lock = asyncio.Lock()

# Legacy-member grandfathering is migration/bootstrap work, not normal
# request-path work. Once a guardian has been reconciled successfully in
# this process, subsequent subscription reads and invite checks skip it.
_premium_ready_guardians: set[str] = set()
_premium_ready_lock = asyncio.Lock()


async def ensure_tables() -> None:
    global _table_ready
    if _table_ready:
        return
    async with _table_lock:
        if _table_ready:
            return
        from app.db.session import async_session
        async with async_session() as session:
            for ddl in _DDL:
                await session.execute(text(ddl))
            await session.commit()
        _table_ready = True


def _require_primary_guardian(actor: User) -> None:
    role = normalize_role(actor.role)
    if role not in {"guardian", "admin"}:
        raise HTTPException(status_code=403, detail="Only the Primary Parent can manage protected-member subscriptions")


def entitlements_for_plan(plan: str) -> dict[str, bool]:
    premium = str(plan).lower() == "premium"
    return {
        "ai_safety_monitoring": True,
        "route_monitoring": True,
        "emergency_sos": True,
        "safe_zones": True,
        "qr_linking": True,
        "mobile_sensors": True,
        "environmental_sensors": True,
        "wearable": premium,
        "wearable_sos": premium,
        "battery_device_sync_alerts": premium,
        "advanced_sensor_monitoring": premium,
        "realtime_guardian_notifications": premium,
        "emergency_escalation": premium,
        "advanced_family_dashboard": premium,
    }


async def _linked_protected_members(session: AsyncSession, guardian_id) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT u.id, u.full_name, u.email, u.role
                FROM users u
                LEFT JOIN guardian_relationships gr
                  ON gr.user_id = u.id
                 AND gr.guardian_user_id = :guardian_id
                 AND gr.is_active = TRUE
                WHERE u.is_active = TRUE
                  AND LOWER(COALESCE(u.role, '')) IN ('child','woman','women','senior','elderly','family','family_member','family-member','member','protected_member')
                  AND (u.guardian_id = :guardian_id OR gr.id IS NOT NULL)
                ORDER BY u.full_name NULLS LAST, u.email
                """
            ),
            {"guardian_id": guardian_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def ensure_existing_members_premium(session: AsyncSession, guardian_id) -> None:
    """Grandfather legacy linked protected members exactly when needed.

    Existing subscription-backed families must not pay the cost of repeatedly
    scanning and re-inserting every protected member on each summary/invite
    request. New protected members are bound authoritatively through the
    subscription invite flow, so this remains only a legacy reconciliation
    safeguard.
    """
    await ensure_tables()

    guardian_key = str(guardian_id)

    if guardian_key in _premium_ready_guardians:
        return

    async with _premium_ready_lock:
        if guardian_key in _premium_ready_guardians:
            return

        # Query ONLY linked protected members that genuinely have no live
        # subscription. For an already-migrated family this is one read and
        # zero writes/commits instead of N no-op INSERTs plus COMMIT.
        members = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT u.id, u.full_name, u.email, u.role
                    FROM users u
                    LEFT JOIN guardian_relationships gr
                      ON gr.user_id = u.id
                     AND gr.guardian_user_id = :guardian_id
                     AND gr.is_active = TRUE
                    WHERE u.is_active = TRUE
                      AND LOWER(COALESCE(u.role, '')) IN (
                          'child',
                          'woman',
                          'women',
                          'senior',
                          'elderly',
                          'family',
                          'family_member',
                          'family-member',
                          'member',
                          'protected_member'
                      )
                      AND (
                          u.guardian_id = :guardian_id
                          OR gr.id IS NOT NULL
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM member_subscriptions s
                          WHERE s.protected_member_user_id = u.id
                            AND s.status IN ('active', 'pending')
                      )
                    ORDER BY u.full_name NULLS LAST, u.email
                    """
                ),
                {"guardian_id": guardian_id},
            )
        ).mappings().all()

        if members:
            for member in members:
                await session.execute(
                    text(
                        """
                        INSERT INTO member_subscriptions (
                            id,
                            guardian_user_id,
                            protected_member_user_id,
                            plan,
                            status,
                            price_monthly,
                            starts_at,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :id,
                            :guardian_id,
                            :member_id,
                            'premium',
                            'active',
                            499,
                            NOW(),
                            NOW(),
                            NOW()
                        )
                        ON CONFLICT (protected_member_user_id)
                        WHERE protected_member_user_id IS NOT NULL
                          AND status IN ('active', 'pending')
                        DO NOTHING
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "guardian_id": guardian_id,
                        "member_id": member["id"],
                    },
                )

            await session.commit()

        # Safe because:
        #   * all currently linked legacy members were checked above;
        #   * new protected members are subscription-bound by invite acceptance;
        #   * a failed reconciliation never reaches this line.
        _premium_ready_guardians.add(guardian_key)


async def _summary_rows_for_guardian(session: AsyncSession, guardian_id):
    """Read subscription summary rows without schema/reconciliation side effects.

    This is the normal hot path. Production already has the subscription tables,
    and current/future subscription-backed families should need only this single
    SELECT. Legacy reconciliation is kept as a fallback only when a guardian has
    no subscription rows yet.
    """
    return (
        await session.execute(
            text(
                """
                SELECT s.id, s.guardian_user_id, s.protected_member_user_id,
                       s.plan, s.status, s.price_monthly, s.starts_at, s.expires_at,
                       s.cancel_at_period_end,
                       u.full_name AS member_name, u.email AS member_email, u.role AS member_role
                FROM member_subscriptions s
                LEFT JOIN users u ON u.id = s.protected_member_user_id
                WHERE s.guardian_user_id = :guardian_id
                ORDER BY (s.protected_member_user_id IS NULL) DESC, s.created_at ASC
                """
            ),
            {"guardian_id": guardian_id},
        )
    ).mappings().all()


async def summary_for_guardian(session: AsyncSession, actor: User) -> dict[str, Any]:
    _require_primary_guardian(actor)

    # Fast path: summary is a pure read. Do not run CREATE INDEX / legacy
    # reconciliation before every first summary request on a fresh Cloud Run
    # instance. That work caused the client-visible Settings/Subscription stall.
    # Existing and future subscription-backed families normally return here
    # after one SELECT.
    try:
        rows = await _summary_rows_for_guardian(session, actor.id)
    except Exception as exc:
        # Fresh/local environments may not have created the Day-6/7 table yet.
        # Preserve the original self-bootstrap behavior only for that specific
        # missing-table case; do not swallow unrelated database errors.
        message = str(exc).lower()
        if "member_subscriptions" not in message or not (
            "does not exist" in message
            or "undefinedtable" in message
            or "undefined table" in message
        ):
            raise
        await session.rollback()
        await ensure_tables()
        rows = await _summary_rows_for_guardian(session, actor.id)

    # Legacy-only fallback. Proper subscription flows create a row before a
    # protected member is added, so current/future accounts do not pay this
    # reconciliation cost. Old linked families with no subscription records are
    # still grandfathered exactly as before.
    if not rows:
        await ensure_existing_members_premium(session, actor.id)
        rows = await _summary_rows_for_guardian(session, actor.id)

    subscriptions: list[dict[str, Any]] = []
    free_slots = 0
    for row in rows:
        plan = str(row["plan"] or "standard").lower()
        status = str(row["status"] or "pending").lower()
        member_id = row["protected_member_user_id"]
        if member_id is None and status == "active":
            free_slots += 1
        subscriptions.append(
            {
                "id": str(row["id"]),
                "protected_member_user_id": str(member_id) if member_id else None,
                "member_name": row["member_name"],
                "member_email": row["member_email"],
                "member_role": row["member_role"],
                "plan": plan,
                "status": status,
                "price_monthly": int(row["price_monthly"] or PLAN_PRICES.get(plan, 299)),
                "starts_at": row["starts_at"].isoformat() if row["starts_at"] else None,
                "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
                "cancel_at_period_end": bool(row["cancel_at_period_end"]),
                "entitlements": entitlements_for_plan(plan) if status == "active" else {},
            }
        )

    return {
        "guardian_user_id": str(actor.id),
        "subscriptions": subscriptions,
        "free_protected_member_slots": free_slots,
        "protected_member_limit_per_subscription": 1,
        "co_parent_included_per_subscription": 1,
        "payment_mode": "deferred_test_state",
        "summary_runtime_version": "client-ready-v1",
    }


async def activate_test_subscription(session: AsyncSession, actor: User, plan: str) -> dict[str, Any]:
    _require_primary_guardian(actor)
    await ensure_tables()
    plan = str(plan or "").strip().lower()
    if plan not in PLAN_PRICES:
        raise HTTPException(status_code=422, detail="Plan must be standard or premium")

    subscription_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO member_subscriptions (
                id, guardian_user_id, protected_member_user_id, plan, status,
                price_monthly, starts_at, created_at, updated_at
            ) VALUES (
                :id, :guardian_id, NULL, :plan, 'active', :price, NOW(), NOW(), NOW()
            )
            """
        ),
        {"id": subscription_id, "guardian_id": actor.id, "plan": plan, "price": PLAN_PRICES[plan]},
    )
    await session.commit()
    return {
        "id": str(subscription_id),
        "plan": plan,
        "status": "active",
        "price_monthly": PLAN_PRICES[plan],
        "protected_member_user_id": None,
        "entitlements": entitlements_for_plan(plan),
    }


async def member_subscription(session: AsyncSession, member_id) -> dict[str, Any] | None:
    await ensure_tables()
    row = (
        await session.execute(
            text(
                """
                SELECT id, guardian_user_id, protected_member_user_id, plan, status,
                       price_monthly, starts_at, expires_at
                FROM member_subscriptions
                WHERE protected_member_user_id = :member_id
                ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, created_at DESC
                LIMIT 1
                """
            ),
            {"member_id": member_id},
        )
    ).mappings().first()
    if not row:
        # Existing linked protected accounts pre-date subscriptions. Grandfather
        # them as Premium for the current integration/UAT phase without any
        # name/email hardcoding. New members are bound through invite slots.
        linked = (
            await session.execute(
                text(
                    """
                    SELECT id, guardian_id, role
                    FROM users
                    WHERE id = :member_id AND is_active = TRUE
                    """
                ),
                {"member_id": member_id},
            )
        ).mappings().first()
        if linked and linked.get("guardian_id") and is_protected_member(linked.get("role")):
            await session.execute(
                text(
                    """
                    INSERT INTO member_subscriptions (
                        id, guardian_user_id, protected_member_user_id, plan, status,
                        price_monthly, starts_at, created_at, updated_at
                    ) VALUES (
                        :id, :guardian_id, :member_id, 'premium', 'active',
                        499, NOW(), NOW(), NOW()
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"id": uuid.uuid4(), "guardian_id": linked["guardian_id"], "member_id": member_id},
            )
            await session.commit()
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, guardian_user_id, protected_member_user_id, plan, status,
                               price_monthly, starts_at, expires_at
                        FROM member_subscriptions
                        WHERE protected_member_user_id = :member_id
                          AND status = 'active'
                        ORDER BY created_at DESC LIMIT 1
                        """
                    ),
                    {"member_id": member_id},
                )
            ).mappings().first()
        if not row:
            return None
    plan = str(row["plan"] or "standard").lower()
    status = str(row["status"] or "pending").lower()
    return {
        "id": str(row["id"]),
        "guardian_user_id": str(row["guardian_user_id"]),
        "protected_member_user_id": str(row["protected_member_user_id"]),
        "plan": plan,
        "status": status,
        "price_monthly": int(row["price_monthly"] or PLAN_PRICES.get(plan, 299)),
        "entitlements": entitlements_for_plan(plan) if status == "active" else {},
    }


async def member_entitlement(session: AsyncSession, member_id, entitlement: str) -> bool:
    sub = await member_subscription(session, member_id)
    if not sub or sub.get("status") != "active":
        return False
    return bool((sub.get("entitlements") or {}).get(entitlement, False))


async def require_member_entitlement(session: AsyncSession, member_id, entitlement: str) -> dict[str, Any]:
    sub = await member_subscription(session, member_id)
    if not sub or sub.get("status") != "active":
        raise HTTPException(status_code=402, detail="An active subscription is required for this protected member")
    if not bool((sub.get("entitlements") or {}).get(entitlement, False)):
        raise HTTPException(status_code=403, detail="Premium subscription required for this feature")
    return sub


async def reserve_slot_for_invite(
    session: AsyncSession,
    actor: User,
    *,
    code: str,
    expires_at,
    purpose: str = "protected_member",
) -> str | None:
    """Reserve one free subscription slot for an invite.

    Co-parent invites do not consume or reserve a protected-member subscription.
    """
    _require_primary_guardian(actor)
    await ensure_tables()
    purpose = str(purpose or "protected_member").strip().lower()
    if purpose not in {"protected_member", "co_parent"}:
        raise HTTPException(status_code=422, detail="Unsupported invite purpose")

    subscription_id = None
    if purpose == "protected_member":
        row = (
            await session.execute(
                text(
                    """
                    SELECT id
                    FROM member_subscriptions
                    WHERE guardian_user_id = :guardian_id
                      AND protected_member_user_id IS NULL
                      AND status = 'active'
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                ),
                {"guardian_id": actor.id},
            )
        ).first()
        if not row:
            raise HTTPException(
                status_code=402,
                detail="NEW_SUBSCRIPTION_REQUIRED: Purchase/activate a Standard or Premium subscription before inviting another protected member.",
            )
        subscription_id = row.id

    await session.execute(
        text(
            """
            INSERT INTO subscription_invite_reservations (
                guardian_user_id, subscription_id, invite_code, purpose, expires_at, created_at
            ) VALUES (
                :guardian_id, :subscription_id, :invite_code, :purpose, :expires_at, NOW()
            )
            ON CONFLICT (guardian_user_id) DO UPDATE
               SET subscription_id = EXCLUDED.subscription_id,
                   invite_code = EXCLUDED.invite_code,
                   purpose = EXCLUDED.purpose,
                   expires_at = EXCLUDED.expires_at,
                   created_at = NOW()
            """
        ),
        {
            "guardian_id": actor.id,
            "subscription_id": subscription_id,
            "invite_code": code,
            "purpose": purpose,
            "expires_at": expires_at,
        },
    )
    return str(subscription_id) if subscription_id else None


async def active_reservation(session: AsyncSession, guardian_id) -> dict[str, Any] | None:
    await ensure_tables()
    row = (
        await session.execute(
            text(
                """
                SELECT guardian_user_id, subscription_id, invite_code, purpose, expires_at
                FROM subscription_invite_reservations
                WHERE guardian_user_id = :guardian_id
                  AND expires_at > NOW()
                """
            ),
            {"guardian_id": guardian_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def clear_invite_reservation(session: AsyncSession, guardian_id, code: str | None = None) -> None:
    await ensure_tables()
    sql = "DELETE FROM subscription_invite_reservations WHERE guardian_user_id = :guardian_id"
    params: dict[str, Any] = {"guardian_id": guardian_id}
    if code:
        sql += " AND UPPER(invite_code) = :code"
        params["code"] = str(code).strip().upper()
    await session.execute(text(sql), params)


async def reservation_for_code(session: AsyncSession, code: str) -> dict[str, Any] | None:
    await ensure_tables()
    row = (
        await session.execute(
            text(
                """
                SELECT guardian_user_id, subscription_id, invite_code, purpose, expires_at
                FROM subscription_invite_reservations
                WHERE UPPER(invite_code) = :code
                LIMIT 1
                """
            ),
            {"code": str(code).strip().upper()},
        )
    ).mappings().first()
    return dict(row) if row else None


async def bind_reserved_subscription(session: AsyncSession, *, code: str, new_user: User) -> None:
    """Consume a protected-member slot only after successful protected join."""
    reservation = await reservation_for_code(session, code)
    if not reservation:
        raise HTTPException(status_code=409, detail="Invite reservation is no longer available")

    purpose = str(reservation.get("purpose") or "protected_member")
    role = normalize_role(new_user.role)

    if role == "co_parent":
        if purpose != "co_parent":
            raise HTTPException(status_code=403, detail="This invite is for a protected member, not a co-parent")
        await clear_invite_reservation(session, reservation["guardian_user_id"], code)
        return

    if not is_protected_member(role):
        raise HTTPException(status_code=403, detail="Unsupported family role for this invite")
    if purpose != "protected_member" or not reservation.get("subscription_id"):
        raise HTTPException(status_code=402, detail="A protected-member subscription slot is required")

    result = await session.execute(
        text(
            """
            UPDATE member_subscriptions
               SET protected_member_user_id = :member_id,
                   updated_at = NOW()
             WHERE id = :subscription_id
               AND guardian_user_id = :guardian_id
               AND protected_member_user_id IS NULL
               AND status = 'active'
         RETURNING id
            """
        ),
        {
            "member_id": new_user.id,
            "subscription_id": reservation["subscription_id"],
            "guardian_id": reservation["guardian_user_id"],
        },
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=409, detail="Subscription slot was already consumed")

    await clear_invite_reservation(session, reservation["guardian_user_id"], code)

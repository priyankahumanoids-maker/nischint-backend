"""Canonical Family Circle onboarding/invite authority for Phase 4.

This is deliberately additive. Legacy ``users.invite_code`` remains available
as a compatibility fallback until all callers move to this service.
"""
from __future__ import annotations

import hashlib
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.age_policy import is_minor
from app.core.family_circle_permissions import (
    PLAN_FAMILY,
    PLAN_INDIVIDUAL,
    PLAN_TRIAL,
    SEAT_GUARDIAN,
    SEAT_MEMBER,
    SEAT_PROTECTED,
)
from app.core.family_circle_roles import CIRCLE_ROLE_ADULT_MEMBER, CIRCLE_ROLE_MINOR
from app.core.family_consent_policy import CURRENT_FAMILY_NOTICE_VERSION
from app.models.family_circle import CircleMembership, FamilyCircle
from app.models.user import User
from app.services.family_circle_audit_service import append_family_audit
from app.services.family_circle_plan_service import (
    CirclePlanError,
    add_membership_with_seat,
    get_plan_shape,
    seat_capacity,
    validate_seat_for_membership,
)
from app.services.family_circle_service import get_active_membership

INVITE_TTL_HOURS = 48
INVITE_CODE_LENGTH = 6
_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class FamilyInviteError(ValueError):
    """Stable domain error for Phase 4 invite/onboarding failures."""


@dataclass(frozen=True)
class InvitePreview:
    code: str
    circle_id: uuid.UUID
    circle_name: str
    owner_name: str
    plan: str
    seat: str
    invitee_kind: str
    tracked: bool
    who_can_see: str
    data_shared: tuple[str, ...]
    expires_at: datetime


def normalize_invite_code(value: object) -> str:
    code = str(value or "").strip().upper()
    if len(code) != INVITE_CODE_LENGTH or any(ch not in _INVITE_ALPHABET for ch in code):
        raise FamilyInviteError("Invalid Family Circle invite code.")
    return code


def invite_code_hash(value: object) -> str:
    code = normalize_invite_code(value)
    return hashlib.sha256(f"family-circle-invite:{code}".encode("utf-8")).hexdigest()


def generate_invite_code() -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def canonical_invite_seat(plan: str, requested_seat: str) -> str:
    plan_value = str(plan or "").strip().lower()
    seat_value = str(requested_seat or "").strip().lower()
    if plan_value == PLAN_FAMILY:
        if seat_value not in {"", SEAT_MEMBER}:
            raise FamilyInviteError("Family plan invites use the Member seat.")
        return SEAT_MEMBER
    if plan_value in {PLAN_TRIAL, PLAN_INDIVIDUAL}:
        if seat_value not in {SEAT_PROTECTED, SEAT_GUARDIAN}:
            raise FamilyInviteError("Trial and Individual invites require a Protected or Guardian seat.")
        return seat_value
    raise FamilyInviteError("Family Circle plan is not initialized.")


def invite_kind_for_dob(date_of_birth) -> str:
    if date_of_birth is None:
        raise FamilyInviteError("Date of birth is required to accept a Family Circle invite.")
    return "minor" if is_minor(date_of_birth) else "adult"


def disclosure_for(plan: str, seat: str, invitee_kind: str) -> tuple[bool, str, tuple[str, ...]]:
    plan_value = str(plan or "").strip().lower()
    seat_value = canonical_invite_seat(plan_value, seat)
    minor = invitee_kind == "minor"

    if plan_value in {PLAN_TRIAL, PLAN_INDIVIDUAL} and seat_value == SEAT_GUARDIAN:
        return (
            False,
            "You can see the Protected member. The Protected member does not see you.",
            ("Protected member alerts", "Protected member SOS", "Protected member permitted safety data"),
        )

    if plan_value in {PLAN_TRIAL, PLAN_INDIVIDUAL}:
        data = ("Live location", "Zones", "SOS", "Alerts") if minor else (
            "Live location", "Zones and routes", "SOS and alerts", "Consented safety data"
        )
        return (
            True,
            "Up to two Guardians in this circle can see your permitted safety data. You do not see Guardians.",
            data,
        )

    if plan_value == PLAN_FAMILY:
        data = ("Live location", "Zones", "SOS", "Alerts") if minor else (
            "Live location", "Zones and routes", "SOS and alerts", "Consented safety data"
        )
        return (
            True,
            "Every Family-plan member can see every other member's permitted safety data.",
            data,
        )

    raise FamilyInviteError("Family Circle plan is not initialized.")


async def _load_circle_and_actor(
    session: AsyncSession,
    actor_user_id: uuid.UUID,
) -> tuple[FamilyCircle, CircleMembership]:
    membership = await get_active_membership(session, actor_user_id)
    if membership is None:
        raise FamilyInviteError("You do not belong to an active Family Circle.")
    circle = await session.get(FamilyCircle, membership.circle_id)
    if circle is None or circle.status != "active" or circle.plan is None:
        raise FamilyInviteError("Family Circle plan is not initialized.")
    return circle, membership


async def _lock_circle(session: AsyncSession, circle_id: uuid.UUID) -> None:
    await session.execute(
        select(FamilyCircle.id).where(FamilyCircle.id == circle_id).with_for_update()
    )


async def _expire_pending_invites(session: AsyncSession, circle_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        text(
            """
            UPDATE family_circle_invites
               SET status = 'expired'
             WHERE circle_id = :circle_id
               AND status = 'pending'
               AND expires_at <= :now
            """
        ),
        {"circle_id": circle_id, "now": now},
    )


async def _pending_invite_count(session: AsyncSession, circle_id: uuid.UUID, seat: str, now: datetime) -> int:
    value = (
        await session.execute(
            text(
                """
                SELECT COUNT(*)
                  FROM family_circle_invites
                 WHERE circle_id = :circle_id
                   AND status = 'pending'
                   AND seat = :seat
                   AND expires_at > :now
                """
            ),
            {"circle_id": circle_id, "seat": seat, "now": now},
        )
    ).scalar_one()
    return int(value or 0)


async def _active_seat_count(session: AsyncSession, circle_id: uuid.UUID, seat: str) -> int:
    value = (
        await session.execute(
            select(func.count())
            .select_from(CircleMembership)
            .where(
                CircleMembership.circle_id == circle_id,
                CircleMembership.status == "active",
                CircleMembership.seat == seat,
            )
        )
    ).scalar_one()
    return int(value or 0)


async def create_invite(
    session: AsyncSession,
    *,
    actor: User,
    requested_seat: str,
    invitee_kind: str = "adult",
    parental_basis: str | None = None,
    parental_verification_ref: str | None = None,
    now: datetime | None = None,
) -> tuple[str, datetime, FamilyCircle, str, str]:
    """Create one 48-hour, single-use, seat-bound invite.

    Pending invites reserve capacity. This prevents two concurrent invite
    creators from overbooking a seat before either invite is accepted.
    """
    circle, actor_membership = await _load_circle_and_actor(session, actor.id)
    if actor_membership.role not in {"owner", "co_admin"}:
        raise FamilyInviteError("Only the Owner or Co-Admin can invite members.")

    kind = str(invitee_kind or "adult").strip().lower()
    if kind not in {"adult", "minor"}:
        raise FamilyInviteError("Invitee type must be adult or minor.")

    seat = canonical_invite_seat(circle.plan, requested_seat)
    if kind == "minor" and seat == SEAT_GUARDIAN:
        raise FamilyInviteError("A Minor cannot occupy a Guardian seat.")

    if kind == "minor":
        # Fail closed until counsel-approved parental proof and high-risk
        # step-up verification are both represented by server-verified
        # artifacts. Caller-supplied strings must never grant parental authority.
        raise FamilyInviteError(
            "Minor invite creation requires verified parental consent and step-up verification; this path is not enabled yet."
        )
    else:
        parental_basis = None
        parental_verification_ref = None

    point = now or datetime.now(timezone.utc)
    if point.tzinfo is None:
        point = point.replace(tzinfo=timezone.utc)

    await _lock_circle(session, circle.id)
    await _expire_pending_invites(session, circle.id, point)

    capacity = seat_capacity(circle.plan, seat)
    occupied = await _active_seat_count(session, circle.id, seat)
    pending = await _pending_invite_count(session, circle.id, seat, point)
    if occupied + pending >= capacity:
        raise FamilyInviteError("This Family Circle seat type is full.")

    expires_at = point + timedelta(hours=INVITE_TTL_HOURS)
    code = ""
    digest = ""
    for _ in range(8):
        candidate = generate_invite_code()
        candidate_hash = invite_code_hash(candidate)
        existing = (
            await session.execute(
                text("SELECT 1 FROM family_circle_invites WHERE code_hash = :code_hash"),
                {"code_hash": candidate_hash},
            )
        ).scalar_one_or_none()
        if existing is None:
            code, digest = candidate, candidate_hash
            break
    if not code:
        raise FamilyInviteError("Could not allocate a unique invite code. Please try again.")

    await session.execute(
        text(
            """
            INSERT INTO family_circle_invites (
                id, circle_id, created_by_user_id, code_hash, seat, invitee_kind,
                status, parental_basis, parental_verification_ref, expires_at, created_at
            ) VALUES (
                :id, :circle_id, :created_by_user_id, :code_hash, :seat, :invitee_kind,
                'pending', :parental_basis, :parental_verification_ref, :expires_at, :created_at
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "circle_id": circle.id,
            "created_by_user_id": actor.id,
            "code_hash": digest,
            "seat": seat,
            "invitee_kind": kind,
            "parental_basis": parental_basis,
            "parental_verification_ref": parental_verification_ref,
            "expires_at": expires_at,
            "created_at": point,
        },
    )
    await append_family_audit(
        session,
        circle_id=circle.id,
        actor_user_id=actor.id,
        subject_user_id=None,
        event_type="invite_created",
        details={"seat": seat, "invitee_kind": kind, "expires_at": expires_at.isoformat()},
    )
    if kind == "minor":
        await append_family_audit(
            session,
            circle_id=circle.id,
            actor_user_id=actor.id,
            subject_user_id=None,
            event_type="parental_consent_recorded",
            details={"basis": parental_basis},
        )
    await session.flush()
    return code, expires_at, circle, seat, kind


async def _invite_row(session: AsyncSession, code: str, *, for_update: bool = False):
    digest = invite_code_hash(code)
    suffix = " FOR UPDATE" if for_update else ""
    result = await session.execute(
        text(
            """
            SELECT i.id, i.circle_id, i.created_by_user_id, i.seat, i.invitee_kind,
                   i.status, i.parental_basis, i.parental_verification_ref, i.expires_at,
                   i.accepted_by_user_id, c.name AS circle_name, c.plan,
                   c.owner_user_id, u.full_name AS owner_name
              FROM family_circle_invites i
              JOIN family_circles c ON c.id = i.circle_id
              JOIN users u ON u.id = c.owner_user_id
             WHERE i.code_hash = :code_hash
            """ + suffix
        ),
        {"code_hash": digest},
    )
    return result.mappings().first()


async def preview_invite(
    session: AsyncSession,
    code: str,
    *,
    now: datetime | None = None,
) -> InvitePreview:
    normalized = normalize_invite_code(code)
    row = await _invite_row(session, normalized)
    if row is None:
        raise FamilyInviteError("Invalid Family Circle invite code.")

    point = now or datetime.now(timezone.utc)
    if point.tzinfo is None:
        point = point.replace(tzinfo=timezone.utc)
    if row["status"] != "pending":
        raise FamilyInviteError("This Family Circle invite is no longer active.")
    if row["expires_at"] <= point:
        await session.execute(
            text("UPDATE family_circle_invites SET status='expired' WHERE id=:id AND status='pending'"),
            {"id": row["id"]},
        )
        await session.flush()
        raise FamilyInviteError("This Family Circle invite has expired.")

    tracked, who_can_see, data_shared = disclosure_for(
        str(row["plan"]), str(row["seat"]), str(row["invitee_kind"])
    )
    return InvitePreview(
        code=normalized,
        circle_id=row["circle_id"],
        circle_name=str(row["circle_name"] or "Family Circle"),
        owner_name=str(row["owner_name"] or "Circle Owner"),
        plan=str(row["plan"]),
        seat=str(row["seat"]),
        invitee_kind=str(row["invitee_kind"]),
        tracked=tracked,
        who_can_see=who_can_see,
        data_shared=data_shared,
        expires_at=row["expires_at"],
    )


async def accept_invite_for_user(
    session: AsyncSession,
    *,
    code: str,
    new_user: User,
    now: datetime | None = None,
) -> CircleMembership:
    """Consume a canonical invite and attach ``new_user`` atomically."""
    normalized = normalize_invite_code(code)
    first = await _invite_row(session, normalized)
    if first is None:
        raise FamilyInviteError("Invalid Family Circle invite code.")

    await _lock_circle(session, first["circle_id"])
    row = await _invite_row(session, normalized, for_update=True)
    if row is None:
        raise FamilyInviteError("Invalid Family Circle invite code.")

    point = now or datetime.now(timezone.utc)
    if point.tzinfo is None:
        point = point.replace(tzinfo=timezone.utc)
    if row["status"] != "pending":
        raise FamilyInviteError("This Family Circle invite has already been used or revoked.")
    if row["expires_at"] <= point:
        await session.execute(
            text("UPDATE family_circle_invites SET status='expired' WHERE id=:id"),
            {"id": row["id"]},
        )
        raise FamilyInviteError("This Family Circle invite has expired.")

    actual_kind = invite_kind_for_dob(new_user.date_of_birth)
    if actual_kind != str(row["invitee_kind"]):
        if actual_kind == "minor":
            raise FamilyInviteError("A Minor can join only with a parent-created Minor invite.")
        raise FamilyInviteError("This invite was created specifically for a Minor.")

    if actual_kind == "minor":
        if not row["parental_basis"] or not row["parental_verification_ref"]:
            raise FamilyInviteError("Verified parental consent is missing for this Minor invite.")
        role = CIRCLE_ROLE_MINOR
    else:
        role = CIRCLE_ROLE_ADULT_MEMBER

    circle = await session.get(FamilyCircle, row["circle_id"])
    if circle is None or circle.status != "active" or circle.plan is None:
        raise FamilyInviteError("Family Circle is not active.")

    try:
        validate_seat_for_membership(circle.plan, str(row["seat"]), role)
        identity = await add_membership_with_seat(
            session,
            circle=circle,
            user=new_user,
            role=role,
            seat=str(row["seat"]),
            created_by_user_id=row["created_by_user_id"],
        )
    except CirclePlanError as exc:
        raise FamilyInviteError(str(exc)) from exc

    membership = await session.get(CircleMembership, identity.membership_id)
    if membership is None:
        raise FamilyInviteError("Family Circle membership could not be created.")

    if actual_kind == "minor":
        # The parent/lawful-guardian evidence belongs to the invite because the
        # Minor account does not exist when the invite is created. Once the
        # account exists, materialize the permitted child-safety consent events
        # for live/background location only. Behavioral AI, microphone and
        # wearable remain unavailable to Minors under Phase 3 policy.
        for purpose in ("location", "background_location"):
            await session.execute(
                text(
                    """
                    INSERT INTO family_consent_events (
                        id, subject_user_id, actor_user_id, purpose, state,
                        notice_version, language, device_id, parental_basis, created_at
                    ) VALUES (
                        :id, :subject_user_id, :actor_user_id, :purpose, 'granted',
                        :notice_version, 'en', NULL, :parental_basis, :created_at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "subject_user_id": new_user.id,
                    "actor_user_id": row["created_by_user_id"],
                    "purpose": purpose,
                    "notice_version": CURRENT_FAMILY_NOTICE_VERSION,
                    "parental_basis": row["parental_basis"],
                    "created_at": point,
                },
            )

    result = await session.execute(
        text(
            """
            UPDATE family_circle_invites
               SET status='accepted', accepted_by_user_id=:user_id, accepted_at=:accepted_at
             WHERE id=:id AND status='pending'
         RETURNING id
            """
        ),
        {"user_id": new_user.id, "accepted_at": point, "id": row["id"]},
    )
    if result.scalar_one_or_none() is None:
        raise FamilyInviteError("This Family Circle invite was already consumed.")
    await append_family_audit(
        session,
        circle_id=circle.id,
        actor_user_id=new_user.id,
        subject_user_id=new_user.id,
        event_type="member_joined",
        details={"seat": str(row["seat"]), "role": role},
    )
    await session.flush()
    return membership


async def revoke_invite(
    session: AsyncSession,
    *,
    actor: User,
    code: str,
    now: datetime | None = None,
) -> bool:
    circle, membership = await _load_circle_and_actor(session, actor.id)
    if membership.role not in {"owner", "co_admin"}:
        raise FamilyInviteError("Only the Owner or Co-Admin can revoke invites.")
    digest = invite_code_hash(code)
    point = now or datetime.now(timezone.utc)
    result = await session.execute(
        text(
            """
            UPDATE family_circle_invites
               SET status='revoked', revoked_at=:now
             WHERE code_hash=:code_hash
               AND circle_id=:circle_id
               AND status='pending'
         RETURNING id
            """
        ),
        {"code_hash": digest, "circle_id": circle.id, "now": point},
    )
    revoked = result.scalar_one_or_none() is not None
    if revoked:
        await append_family_audit(
            session,
            circle_id=circle.id,
            actor_user_id=actor.id,
            subject_user_id=None,
            event_type="invite_revoked",
            details={},
        )
    await session.flush()
    return revoked


async def seat_usage(session: AsyncSession, circle: FamilyCircle, *, now: datetime | None = None) -> dict[str, dict[str, int]]:
    point = now or datetime.now(timezone.utc)
    await _expire_pending_invites(session, circle.id, point)
    shape = get_plan_shape(str(circle.plan))
    result: dict[str, dict[str, int]] = {}
    for seat, capacity in shape.capacities.items():
        active = await _active_seat_count(session, circle.id, seat)
        pending = await _pending_invite_count(session, circle.id, seat, point)
        result[seat] = {
            "active": active,
            "pending_invites": pending,
            "capacity": capacity,
            "available": max(0, capacity - active - pending),
        }
    return result


__all__ = [
    "INVITE_TTL_HOURS",
    "FamilyInviteError",
    "InvitePreview",
    "normalize_invite_code",
    "invite_code_hash",
    "generate_invite_code",
    "canonical_invite_seat",
    "invite_kind_for_dob",
    "disclosure_for",
    "create_invite",
    "preview_invite",
    "accept_invite_for_user",
    "revoke_invite",
    "seat_usage",
]

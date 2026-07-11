# Guardian Network API — Relationship graph & emergency contacts
import os
import uuid as uuid_mod
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy import select, and_, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.roles import require_role
from app.models.user import User
from app.models.guardian_network import GuardianRelationship, EmergencyContact, GuardianInvite
from app.services.email_service import send_guardian_invite_email

router = APIRouter(prefix="/guardian-network", tags=["Guardian Network"])


# ── Pydantic schemas ──

class GuardianRelationshipCreate(BaseModel):
    guardian_user_id: Optional[str] = None
    relationship_type: str = Field(..., pattern="^(parent|friend|sibling|spouse|campus_security|institution)$")
    guardian_name: str = Field(..., min_length=1, max_length=255)
    guardian_phone: Optional[str] = None
    guardian_email: Optional[str] = None
    priority: int = Field(1, ge=1, le=20)
    is_primary: bool = False
    notification_channels: List[str] = ["push", "sms"]


class GuardianRelationshipUpdate(BaseModel):
    relationship_type: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    guardian_email: Optional[str] = None
    priority: Optional[int] = None
    is_primary: Optional[bool] = None
    notification_channels: Optional[List[str]] = None
    is_active: Optional[bool] = None


class EmergencyContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=1, max_length=20)
    email: Optional[str] = None
    relationship_type: str = Field("emergency_services", pattern="^(emergency_services|hospital|police|neighbor|other)$")
    priority: int = Field(10, ge=1, le=50)
    notes: Optional[str] = None


class EmergencyContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    relationship_type: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


def _serialize_relationship(r: GuardianRelationship) -> dict:
    return {
        "id": str(r.id),
        "user_id": str(r.user_id),
        "guardian_user_id": str(r.guardian_user_id) if r.guardian_user_id else None,
        "relationship_type": r.relationship_type,
        "guardian_name": r.guardian_name,
        "guardian_phone": r.guardian_phone,
        "guardian_email": r.guardian_email,
        "priority": r.priority,
        "is_primary": r.is_primary,
        "notification_channels": r.notification_channels,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _serialize_contact(c: EmergencyContact) -> dict:
    return {
        "id": str(c.id),
        "user_id": str(c.user_id),
        "name": c.name,
        "phone": c.phone,
        "email": c.email,
        "relationship_type": c.relationship_type,
        "priority": c.priority,
        "is_active": c.is_active,
        "notes": c.notes,
        "created_at": c.created_at.isoformat(),
    }


# ── Guardian Relationships ──

@router.get("/")
async def list_guardian_network(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """List all guardians for the current user."""
    rows = (await session.execute(
        select(GuardianRelationship)
        .where(and_(
            GuardianRelationship.user_id == user.id,
            GuardianRelationship.is_active == True,
        ))
        .order_by(GuardianRelationship.priority)
    )).scalars().all()
    return {"guardians": [_serialize_relationship(r) for r in rows], "total": len(rows)}


@router.post("/", status_code=201)
async def add_guardian(
    body: GuardianRelationshipCreate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Add a guardian to the user's network."""
    guardian_user_id = None
    if body.guardian_user_id:
        try:
            guardian_user_id = uuid_mod.UUID(body.guardian_user_id)
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid guardian_user_id format")
        existing = (await session.execute(
            select(User).where(User.id == guardian_user_id)
        )).scalar_one_or_none()
        if not existing:
            raise HTTPException(404, "Guardian user not found")

    # If is_primary, unset any existing primary
    if body.is_primary:
        await session.execute(
            update(GuardianRelationship)
            .where(and_(
                GuardianRelationship.user_id == user.id,
                GuardianRelationship.is_primary == True,
            ))
            .values(is_primary=False)
        )

    rel = GuardianRelationship(
        user_id=user.id,
        guardian_user_id=guardian_user_id,
        relationship_type=body.relationship_type,
        guardian_name=body.guardian_name,
        guardian_phone=body.guardian_phone,
        guardian_email=body.guardian_email,
        priority=body.priority,
        is_primary=body.is_primary,
        notification_channels=body.notification_channels,
    )
    session.add(rel)
    await session.commit()
    await session.refresh(rel)
    return _serialize_relationship(rel)


@router.put("/{relationship_id}")
async def update_guardian(
    relationship_id: str,
    body: GuardianRelationshipUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Update a guardian relationship."""
    try:
        rid = uuid_mod.UUID(relationship_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid ID format")

    rel = (await session.execute(
        select(GuardianRelationship).where(and_(
            GuardianRelationship.id == rid,
            GuardianRelationship.user_id == user.id,
        ))
    )).scalar_one_or_none()
    if not rel:
        raise HTTPException(404, "Guardian relationship not found")

    updates = body.model_dump(exclude_unset=True)
    if "is_primary" in updates and updates["is_primary"]:
        await session.execute(
            update(GuardianRelationship)
            .where(and_(
                GuardianRelationship.user_id == user.id,
                GuardianRelationship.is_primary == True,
                GuardianRelationship.id != rid,
            ))
            .values(is_primary=False)
        )

    for k, v in updates.items():
        setattr(rel, k, v)
    rel.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(rel)
    return _serialize_relationship(rel)


@router.delete("/{relationship_id}")
async def remove_guardian(
    relationship_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Remove a guardian from network (soft delete)."""
    try:
        rid = uuid_mod.UUID(relationship_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid ID format")

    result = await session.execute(
        update(GuardianRelationship)
        .where(and_(
            GuardianRelationship.id == rid,
            GuardianRelationship.user_id == user.id,
        ))
        .values(is_active=False, updated_at=datetime.now(timezone.utc))
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Guardian relationship not found")
    await session.commit()
    return {"status": "removed", "id": relationship_id}


@router.get("/escalation-chain")
async def get_escalation_chain(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Get ordered escalation chain for the user (guardians + emergency contacts)."""
    guardians = (await session.execute(
        select(GuardianRelationship)
        .where(and_(
            GuardianRelationship.user_id == user.id,
            GuardianRelationship.is_active == True,
        ))
        .order_by(GuardianRelationship.priority)
    )).scalars().all()

    contacts = (await session.execute(
        select(EmergencyContact)
        .where(and_(
            EmergencyContact.user_id == user.id,
            EmergencyContact.is_active == True,
        ))
        .order_by(EmergencyContact.priority)
    )).scalars().all()

    chain = []
    for g in guardians:
        chain.append({
            "level": g.priority,
            "type": "guardian",
            "name": g.guardian_name,
            "phone": g.guardian_phone,
            "email": g.guardian_email,
            "relationship": g.relationship_type,
            "channels": g.notification_channels,
            "is_primary": g.is_primary,
            "id": str(g.id),
        })
    for c in contacts:
        chain.append({
            "level": c.priority,
            "type": "emergency_contact",
            "name": c.name,
            "phone": c.phone,
            "email": c.email,
            "relationship": c.relationship_type,
            "channels": ["call", "sms"],
            "is_primary": False,
            "id": str(c.id),
        })
    chain.sort(key=lambda x: x["level"])
    return {"escalation_chain": chain, "total": len(chain)}


# ── Emergency Contacts ──

@router.get("/emergency-contacts")
async def list_emergency_contacts(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """List emergency contacts for the user."""
    rows = (await session.execute(
        select(EmergencyContact)
        .where(and_(
            EmergencyContact.user_id == user.id,
            EmergencyContact.is_active == True,
        ))
        .order_by(EmergencyContact.priority)
    )).scalars().all()
    return {"contacts": [_serialize_contact(c) for c in rows], "total": len(rows)}


@router.post("/emergency-contacts", status_code=201)
async def add_emergency_contact(
    body: EmergencyContactCreate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Add an emergency contact."""
    contact = EmergencyContact(
        user_id=user.id,
        name=body.name,
        phone=body.phone,
        email=body.email,
        relationship_type=body.relationship_type,
        priority=body.priority,
        notes=body.notes,
    )
    session.add(contact)
    await session.commit()
    await session.refresh(contact)
    return _serialize_contact(contact)


@router.put("/emergency-contacts/{contact_id}")
async def update_emergency_contact(
    contact_id: str,
    body: EmergencyContactUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Update an emergency contact."""
    try:
        cid = uuid_mod.UUID(contact_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid ID format")

    contact = (await session.execute(
        select(EmergencyContact).where(and_(
            EmergencyContact.id == cid,
            EmergencyContact.user_id == user.id,
        ))
    )).scalar_one_or_none()
    if not contact:
        raise HTTPException(404, "Emergency contact not found")

    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(contact, k, v)
    await session.commit()
    await session.refresh(contact)
    return _serialize_contact(contact)


@router.delete("/emergency-contacts/{contact_id}")
async def delete_emergency_contact(
    contact_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Delete an emergency contact (soft delete)."""
    try:
        cid = uuid_mod.UUID(contact_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid ID format")

    result = await session.execute(
        update(EmergencyContact)
        .where(and_(
            EmergencyContact.id == cid,
            EmergencyContact.user_id == user.id,
        ))
        .values(is_active=False)
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Emergency contact not found")
    await session.commit()
    return {"status": "removed", "id": contact_id}



# ── Guardian Invite Links ──

INVITE_EXPIRY_HOURS = 48


class InviteCreate(BaseModel):
    guardian_email: Optional[str] = None
    guardian_phone: Optional[str] = None
    guardian_name: Optional[str] = None
    relationship_type: str = Field("friend", pattern="^(parent|friend|sibling|spouse|campus_security|institution|other)$")


class InviteAccept(BaseModel):
    """Accepted by the invitee (who is now authenticated)."""
    pass  # user info comes from auth token


def _serialize_invite(inv: GuardianInvite) -> dict:
    return {
        "id": str(inv.id),
        "inviter_user_id": str(inv.inviter_user_id),
        "inviter_name": inv.inviter_name,
        "guardian_email": inv.guardian_email,
        "guardian_phone": inv.guardian_phone,
        "guardian_name": inv.guardian_name,
        "relationship_type": inv.relationship_type,
        "invite_token": inv.invite_token,
        "status": inv.status,
        "created_at": inv.created_at.isoformat(),
        "expires_at": inv.expires_at.isoformat(),
        "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
    }


@router.post("/invite", status_code=201)
async def create_invite(
    body: InviteCreate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Create a guardian invite link. Returns the invite token and shareable URL."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    invite = GuardianInvite(
        inviter_user_id=user.id,
        guardian_email=body.guardian_email,
        guardian_phone=body.guardian_phone,
        guardian_name=body.guardian_name,
        relationship_type=body.relationship_type,
        invite_token=token,
        inviter_name=user.full_name or user.email,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(hours=INVITE_EXPIRY_HOURS),
    )
    session.add(invite)
    await session.flush()

    # Send invite email if guardian email is provided
    invite_url = f"/invite/{token}"
    email_sent = False
    if body.guardian_email:
        from fastapi import Request
        base_url = os.environ.get("APP_BASE_URL", "")
        full_invite_url = f"{base_url}{invite_url}" if base_url else invite_url
        email_sent = send_guardian_invite_email(
            to_email=body.guardian_email,
            inviter_name=user.full_name or user.email,
            guardian_name=body.guardian_name,
            relationship=body.relationship_type,
            invite_url=full_invite_url,
        )

    # Send push notification to invited guardian (if they're already a user)
    push_sent = False
    try:
        if body.guardian_email:
            from app.services.user_service import get_user_by_email
            guardian_user = await get_user_by_email(session, body.guardian_email)
            if guardian_user:
                from app.services.notification_service import NotificationService
                from app.db.session import async_session
                ns = NotificationService(async_session)
                await ns.send_invite_notification(
                    guardian_id=str(guardian_user.id),
                    inviter_name=user.full_name or user.email,
                )
                push_sent = True
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Invite push notification skipped: {e}")

    return {
        "invite": _serialize_invite(invite),
        "invite_url": invite_url,
        "email_sent": email_sent,
        "push_sent": push_sent,
        "share_message": (
            f"You've been invited to join {user.full_name or user.email}'s safety network on Nischint. "
            f"Install the app and stay connected: "
        ),
    }


@router.get("/invites")
async def list_invites(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """List all invites sent by the current user."""
    rows = (await session.execute(
        select(GuardianInvite)
        .where(GuardianInvite.inviter_user_id == user.id)
        .order_by(GuardianInvite.created_at.desc())
    )).scalars().all()
    return {"invites": [_serialize_invite(inv) for inv in rows], "total": len(rows)}


@router.get("/invite/{token}")
async def get_invite(
    token: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Public endpoint — get invite details by token. No auth required."""
    invite = (await session.execute(
        select(GuardianInvite).where(GuardianInvite.invite_token == token)
    )).scalar_one_or_none()

    if not invite:
        raise HTTPException(404, "Invite not found")

    now = datetime.now(timezone.utc)
    if invite.status == "expired" or (invite.expires_at and invite.expires_at < now):
        if invite.status != "expired":
            invite.status = "expired"
            await session.commit()
        raise HTTPException(410, "This invite has expired")

    if invite.status == "accepted":
        return {
            "invite": _serialize_invite(invite),
            "already_accepted": True,
        }

    if invite.status == "revoked":
        raise HTTPException(410, "This invite has been revoked")

    return {
        "invite": _serialize_invite(invite),
        "already_accepted": False,
    }


@router.post("/invite/{token}/accept")
async def accept_invite(
    token: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Accept a guardian invite. Creates the guardian relationship."""
    invite = (await session.execute(
        select(GuardianInvite).where(GuardianInvite.invite_token == token)
    )).scalar_one_or_none()

    if not invite:
        raise HTTPException(404, "Invite not found")

    now = datetime.now(timezone.utc)
    if invite.status != "pending":
        raise HTTPException(400, f"Invite is already {invite.status}")
    if invite.expires_at and invite.expires_at < now:
        invite.status = "expired"
        await session.commit()
        raise HTTPException(410, "This invite has expired")

    # Don't allow self-invite
    if invite.inviter_user_id == user.id:
        raise HTTPException(400, "Cannot accept your own invite")

    # Check for duplicate relationship
    existing = (await session.execute(
        select(GuardianRelationship).where(and_(
            GuardianRelationship.user_id == invite.inviter_user_id,
            GuardianRelationship.guardian_user_id == user.id,
            GuardianRelationship.is_active == True,
        ))
    )).scalar_one_or_none()

    if existing:
        invite.status = "accepted"
        invite.accepted_at = now
        invite.accepted_by_user_id = user.id
        await session.commit()
        return {"status": "already_guardian", "message": "You are already in this safety network"}

    # Determine next priority
    max_priority_row = (await session.execute(
        select(GuardianRelationship.priority)
        .where(and_(
            GuardianRelationship.user_id == invite.inviter_user_id,
            GuardianRelationship.is_active == True,
        ))
        .order_by(GuardianRelationship.priority.desc())
        .limit(1)
    )).scalar_one_or_none()
    next_priority = (max_priority_row or 0) + 1

    # Create the guardian relationship
    relationship = GuardianRelationship(
        user_id=invite.inviter_user_id,
        guardian_user_id=user.id,
        relationship_type=invite.relationship_type,
        guardian_name=user.full_name or user.email,
        guardian_email=user.email,
        priority=next_priority,
        is_primary=False,
        notification_channels=["push", "sms"],
    )
    session.add(relationship)

    # Update invite status
    invite.status = "accepted"
    invite.accepted_at = now
    invite.accepted_by_user_id = user.id

    await session.flush()

    return {
        "status": "accepted",
        "relationship_id": str(relationship.id),
        "inviter_name": invite.inviter_name,
        "message": f"You are now a guardian for {invite.inviter_name}",
    }


@router.delete("/invite/{token}")
async def revoke_invite(
    token: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator", "guardian")),
):
    """Revoke a pending invite."""
    invite = (await session.execute(
        select(GuardianInvite).where(and_(
            GuardianInvite.invite_token == token,
            GuardianInvite.inviter_user_id == user.id,
        ))
    )).scalar_one_or_none()

    if not invite:
        raise HTTPException(404, "Invite not found")
    if invite.status != "pending":
        raise HTTPException(400, f"Invite is already {invite.status}")

    invite.status = "revoked"
    await session.commit()
    return {"status": "revoked"}

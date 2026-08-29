# Admin Panel API — User Management, Facility Management, System Health
# All endpoints require admin role.
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.rbac import require_role
from app.core.product_roles import CANONICAL_ROLES, normalize_role
from app.models.user import User
from app.models.facility import Facility
from app.services import user_cache
from app.services.auth_session_service import (
    bump_user_token_epoch,
    revoke_all_auth_sessions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Admin-only: all MUTATING operations (create/update/delete/role-change).
# These can escalate privileges, change billing surface, or alter system config,
# so they must remain strictly admin.
_admin_role = require_role(["admin"])

# Admin OR Operator: all READ-ONLY list/detail views + dashboard stats.
# Operators (control-room role) need visibility into users, facilities, and
# system health to do their jobs. No mutation possible through these paths.
_read_role = require_role(["admin", "operator"])


# ── Schemas ──

_ADMIN_ROLE_PATTERN = "^(" + "|".join(sorted(CANONICAL_ROLES)) + ")$"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    phone: Optional[str] = None
    password: str = Field(..., min_length=6)
    role: str = Field("guardian", pattern=_ADMIN_ROLE_PATTERN)
    facility_id: Optional[str] = None


class UserUpdateRole(BaseModel):
    role: str = Field(..., pattern=_ADMIN_ROLE_PATTERN)


class UserUpdateFacility(BaseModel):
    facility_id: Optional[str] = None


class UserUpdateStatus(BaseModel):
    is_active: bool


class FacilityCreate(BaseModel):
    name: str = Field(..., max_length=200)
    code: str = Field(..., max_length=50)
    facility_type: str = Field("home", pattern="^(home|hospital|elder_care|community|smart_city)$")
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    max_users: Optional[int] = None


class FacilityUpdate(BaseModel):
    name: Optional[str] = None
    facility_type: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    max_users: Optional[int] = None


# ══════════════════════════════════════════════
# USER MANAGEMENT
# ══════════════════════════════════════════════

@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None),
    facility_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_read_role),
):
    """List all users with filtering, search, and pagination."""
    query = select(User)

    if role:
        query = query.where(User.role == normalize_role(role))
    if facility_id:
        query = query.where(User.facility_id == facility_id)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if search:
        like_pat = f"%{search}%"
        query = query.where(
            (User.email.ilike(like_pat)) | (User.full_name.ilike(like_pat))
        )

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_q)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    total_pages = max(1, (total + page_size - 1) // page_size)
    query = query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    result = await session.execute(query)
    users = result.scalars().all()

    return {
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "role": u.role,
                "facility_id": u.facility_id,
                "phone": u.phone,
                "cognito_sub": u.cognito_sub,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    body: UserUpdateRole,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_admin_role),
):
    """Update a user's role."""
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = user.role
    user.role = normalize_role(body.role)
    await session.flush()

    # Sync to Cognito groups if possible
    try:
        await _sync_cognito_role(user.email, old_role, user.role)
    except Exception as e:
        logger.warning(f"Failed to sync Cognito role for {user.email}: {e}")

    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "previous_role": old_role,
    }


@router.put("/users/{user_id}/facility")
async def update_user_facility(
    user_id: str,
    body: UserUpdateFacility,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_admin_role),
):
    """Assign a user to a facility."""
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate facility exists if assigning
    if body.facility_id:
        fac_stmt = select(Facility).where(Facility.id == uuid.UUID(body.facility_id))
        fac = (await session.execute(fac_stmt)).scalar_one_or_none()
        if not fac:
            raise HTTPException(status_code=404, detail="Facility not found")

    user.facility_id = body.facility_id
    await session.flush()

    return {
        "id": str(user.id),
        "email": user.email,
        "facility_id": user.facility_id,
    }


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_read_role),
):
    """Get detailed user info."""
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "facility_id": user.facility_id,
        "phone": user.phone,
        "cognito_sub": user.cognito_sub,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_admin_role),
):
    """Admin-initiated user creation with role and facility assignment."""
    # Check email uniqueness
    existing = (await session.execute(
        select(User).where(User.email == body.email)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Validate facility if provided
    if body.facility_id:
        fac = (await session.execute(
            select(Facility).where(Facility.id == uuid.UUID(body.facility_id))
        )).scalar_one_or_none()
        if not fac:
            raise HTTPException(status_code=404, detail="Facility not found")

    # Hash password — async-offloaded so bcrypt's ~150ms CPU cost
    # doesn't block the asyncio event loop under admin-onboarding bursts.
    from app.services.user_service import hash_password_async
    hashed = await hash_password_async(body.password)

    new_user = User(
        email=body.email,
        full_name=body.full_name,
        phone=body.phone,
        password_hash=hashed,
        role=normalize_role(body.role),
        facility_id=body.facility_id,
        is_active=True,
    )
    session.add(new_user)
    await session.flush()

    logger.info(f"Admin created user: {body.email} (role={new_user.role})")

    return {
        "id": str(new_user.id),
        "email": new_user.email,
        "full_name": new_user.full_name,
        "role": new_user.role,
        "facility_id": new_user.facility_id,
        "is_active": new_user.is_active,
    }


@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    body: UserUpdateStatus,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_admin_role),
):
    """Activate or deactivate a user."""
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    previous_active = bool(user.is_active)
    user.is_active = body.is_active
    await session.flush()

    # AUTH-04: an explicit admin deactivation must terminate every durable
    # session immediately instead of waiting for access-token expiry.  A token
    # epoch bump also invalidates pre-AUTH-04 credentials.  Re-enabling the
    # account does not resurrect any old session; the user must sign in again.
    revoked_sessions = 0
    if previous_active and not body.is_active:
        revoked_sessions = await revoke_all_auth_sessions(
            session,
            user.id,
            reason="admin_deactivated",
        )
        await bump_user_token_epoch(session, user.id)

    user_cache.invalidate_user_keys(
        str(user.id),
        str(getattr(user, "cognito_sub", "") or ""),
    )

    return {
        "id": str(user.id),
        "email": user.email,
        "is_active": user.is_active,
        "revoked_sessions": revoked_sessions,
    }


# ══════════════════════════════════════════════
# FACILITY MANAGEMENT
# ══════════════════════════════════════════════

@router.get("/facilities")
async def list_facilities(
    is_active: Optional[bool] = Query(None),
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_read_role),
):
    """List all facilities."""
    query = select(Facility)
    if is_active is not None:
        query = query.where(Facility.is_active == is_active)
    query = query.order_by(Facility.created_at.desc())

    result = await session.execute(query)
    facilities = result.scalars().all()

    # Count users per facility
    counts = {}
    for fac in facilities:
        cnt_q = select(func.count()).select_from(User).where(User.facility_id == str(fac.id))
        cnt = (await session.execute(cnt_q)).scalar() or 0
        counts[str(fac.id)] = cnt

    return {
        "facilities": [
            {
                "id": str(f.id),
                "name": f.name,
                "code": f.code,
                "facility_type": f.facility_type,
                "address": f.address,
                "city": f.city,
                "state": f.state,
                "phone": f.phone,
                "email": f.email,
                "is_active": f.is_active,
                "max_users": f.max_users,
                "user_count": counts.get(str(f.id), 0),
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facilities
        ],
        "total": len(facilities),
    }


@router.post("/facilities", status_code=status.HTTP_201_CREATED)
async def create_facility(
    body: FacilityCreate,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_admin_role),
):
    """Create a new facility."""
    # Check code uniqueness
    existing = (await session.execute(
        select(Facility).where(Facility.code == body.code)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Facility code already exists")

    facility = Facility(**body.model_dump())
    session.add(facility)
    await session.flush()

    return {
        "id": str(facility.id),
        "name": facility.name,
        "code": facility.code,
        "facility_type": facility.facility_type,
        "is_active": facility.is_active,
        "created_at": facility.created_at.isoformat() if facility.created_at else None,
    }


@router.put("/facilities/{facility_id}")
async def update_facility(
    facility_id: str,
    body: FacilityUpdate,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_admin_role),
):
    """Update a facility."""
    stmt = select(Facility).where(Facility.id == uuid.UUID(facility_id))
    fac = (await session.execute(stmt)).scalar_one_or_none()
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(fac, key, val)
    await session.flush()

    return {
        "id": str(fac.id),
        "name": fac.name,
        "code": fac.code,
        "is_active": fac.is_active,
    }


@router.delete("/facilities/{facility_id}")
async def delete_facility(
    facility_id: str,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_admin_role),
):
    """Delete a facility (unassigns all users first)."""
    stmt = select(Facility).where(Facility.id == uuid.UUID(facility_id))
    fac = (await session.execute(stmt)).scalar_one_or_none()
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found")

    # Unassign users
    await session.execute(
        update(User).where(User.facility_id == facility_id).values(facility_id=None)
    )

    await session.delete(fac)
    await session.flush()

    return {"deleted": True, "facility_id": facility_id}


@router.patch("/facilities/{facility_id}/status")
async def toggle_facility_status(
    facility_id: str,
    body: UserUpdateStatus,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_admin_role),
):
    """Toggle facility active/inactive status."""
    stmt = select(Facility).where(Facility.id == uuid.UUID(facility_id))
    fac = (await session.execute(stmt)).scalar_one_or_none()
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found")

    fac.is_active = body.is_active
    await session.flush()

    return {
        "id": str(fac.id),
        "name": fac.name,
        "is_active": fac.is_active,
    }


# ══════════════════════════════════════════════
# SYSTEM HEALTH
# ══════════════════════════════════════════════

@router.get("/system-health")
async def system_health(
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_read_role),
):
    """System health overview — user counts, facility counts, DB stats."""
    # User stats
    total_users = (await session.execute(select(func.count()).select_from(User))).scalar() or 0

    role_counts = {}
    for role in sorted(CANONICAL_ROLES):
        cnt = (await session.execute(
            select(func.count()).select_from(User).where(User.role == role)
        )).scalar() or 0
        role_counts[role] = cnt

    # Facility stats
    total_facilities = (await session.execute(select(func.count()).select_from(Facility))).scalar() or 0
    active_facilities = (await session.execute(
        select(func.count()).select_from(Facility).where(Facility.is_active.is_(True))
    )).scalar() or 0

    # Users with Cognito
    cognito_linked = (await session.execute(
        select(func.count()).select_from(User).where(User.cognito_sub.isnot(None))
    )).scalar() or 0

    # Users with facility
    assigned_to_facility = (await session.execute(
        select(func.count()).select_from(User).where(User.facility_id.isnot(None))
    )).scalar() or 0

    # DB connectivity
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    # Cognito status
    from app.core.cognito import is_cognito_enabled
    from app.core.config import settings

    return {
        "status": "healthy" if db_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "users": {
            "total": total_users,
            "by_role": role_counts,
            "cognito_linked": cognito_linked,
            "assigned_to_facility": assigned_to_facility,
        },
        "facilities": {
            "total": total_facilities,
            "active": active_facilities,
        },
        "services": {
            "database": "connected" if db_ok else "error",
            "cognito": "enabled" if is_cognito_enabled() else "disabled",
            "cognito_pool": settings.cognito_user_pool_id if is_cognito_enabled() else None,
            "google_oauth": "enabled" if settings.google_client_id else "disabled",
        },
    }


# ══════════════════════════════════════════════
# ROLE STATS (quick overview)
# ══════════════════════════════════════════════

@router.get("/stats")
async def admin_stats(
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(_read_role),
):
    """Quick stats for admin dashboard cards."""
    total_users = (await session.execute(select(func.count()).select_from(User))).scalar() or 0
    total_facilities = (await session.execute(select(func.count()).select_from(Facility))).scalar() or 0
    active_facilities = (await session.execute(
        select(func.count()).select_from(Facility).where(Facility.is_active.is_(True))
    )).scalar() or 0

    return {
        "total_users": total_users,
        "total_facilities": total_facilities,
        "active_facilities": active_facilities,
    }


# ── Helpers ──

async def _sync_cognito_role(email: str, old_role: str, new_role: str):
    """Sync role change to Cognito groups."""
    from app.core.cognito import is_cognito_enabled
    if not is_cognito_enabled():
        return

    from app.core.config import settings
    import boto3

    client = boto3.client(
        "cognito-idp",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    pool_id = settings.cognito_user_pool_id

    # Remove old group
    if old_role:
        try:
            client.admin_remove_user_from_group(
                UserPoolId=pool_id, Username=email, GroupName=old_role,
            )
        except Exception:
            pass

    # Add new group
    try:
        client.admin_add_user_to_group(
            UserPoolId=pool_id, Username=email, GroupName=new_role,
        )
    except Exception as e:
        logger.error(f"Failed to add {email} to Cognito group {new_role}: {e}")


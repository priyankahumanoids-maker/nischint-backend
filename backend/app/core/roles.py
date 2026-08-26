# Role-Based Access Control
from functools import wraps
from fastapi import HTTPException, status, Depends
from app.api.deps import get_current_user
from app.models.user import User
from app.core.product_roles import normalize_role, normalize_roles


def require_role(*allowed_roles):
    """Dependency that checks if the current user has one of the allowed roles."""
    normalized_allowed = normalize_roles(allowed_roles)

    async def role_checker(current_user: User = Depends(get_current_user)):
        if normalize_role(current_user.role) not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return role_checker

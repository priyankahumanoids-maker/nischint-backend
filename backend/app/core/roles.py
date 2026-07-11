# Role-Based Access Control
from functools import wraps
from fastapi import HTTPException, status, Depends
from app.api.deps import get_current_user
from app.models.user import User


def require_role(*allowed_roles):
    """Dependency that checks if the current user has one of the allowed roles."""
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return role_checker

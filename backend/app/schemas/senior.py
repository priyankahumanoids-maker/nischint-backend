# Senior Schemas
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SeniorCreate(BaseModel):
    """Schema for creating a new senior."""
    full_name: str
    age: Optional[int] = None
    medical_notes: Optional[str] = None


class SeniorResponse(BaseModel):
    """Schema for senior response."""
    id: UUID
    full_name: str
    age: Optional[int] = None
    medical_notes: Optional[str] = None
    guardian_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

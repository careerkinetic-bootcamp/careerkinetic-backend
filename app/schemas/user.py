import uuid
from typing import Any

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    auth_provider: str
    profile_data: dict[str, Any] | None

    class Config:
        from_attributes = True


class AuthCallbackResponse(UserResponse):
    access_token: str
    token_type: str = "bearer"


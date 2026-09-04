import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, UUID, Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONB_TYPE = JSON().with_variant(JSONB, "postgresql")


class User(Base):
    __tablename__ = "users"

    # Primary key matches Supabase auth.users UUID — NOT auto-generated
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    auth_provider: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_login_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    password_changes_today: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_password_change: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Store profiles, backgrounds, URLs in this JSONB column
    profile_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB_TYPE, nullable=True, default=dict
    )

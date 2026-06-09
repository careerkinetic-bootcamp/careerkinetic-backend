from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.domain import User
from app.schemas.user import UserResponse

router = APIRouter(tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


@router.get(
    "/",
    response_model=UserResponse,
    summary="Retrieve current user",
    description=(
        "Returns the active user profile data via standard Bearer "
        "token validation against Supabase Auth."
    ),
)
async def read_users_me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user


@router.post(
    "/sync",
    response_model=UserResponse,
    summary="Sync Supabase user to local profile",
    description=(
        "Called by the frontend after a Supabase login or signup. "
        "Decodes the Supabase JWT, extracts the user ID and email, "
        "and upserts a row in the public.users table."
    ),
)
async def sync_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    supabase_uid = payload.get("sub")
    email = payload.get("email", "")

    if not supabase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
        )

    # Check if user already exists in our profile table
    stmt = select(User).where(User.id == supabase_uid)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user:
        # First login — create a profile row linked to Supabase auth.users
        user = User(id=supabase_uid, email=email, role="user")
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user

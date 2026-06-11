import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.domain import User
from app.schemas.user import UserResponse

router = APIRouter(tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


# --- Request/Response Schemas ---
class CallbackRequest(BaseModel):
    code: str
    provider: str


class UpdateProfileRequest(BaseModel):
    profile_data: dict[str, Any]


# --- Helpers ---
def create_access_token(user_id: str, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expire,
    }
    encoded_jwt = jwt.encode(
        payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


# --- Endpoints ---


@router.get(
    "/",
    response_model=UserResponse,
    summary="Retrieve current user",
    description=(
        "Returns the active user profile data by validating the HttpOnly cookie."
    ),
)
async def read_users_me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user


@router.get(
    "/google/url",
    summary="Get Google Login Redirect URL",
)
async def get_google_url():
    """
    Constructs and returns the Google OAuth Authorization Code Flow URL.
    """
    if not settings.google_client_id:
        raise HTTPException(
            status_code=500, detail="Google client credentials are not configured."
        )
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?response_type=code"
        f"&client_id={settings.google_client_id}"
        f"&redirect_uri={settings.google_redirect_uri}"
        f"&scope=openid%20email%20profile"
        f"&state=google"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    return {"url": auth_url}


@router.get(
    "/github/url",
    summary="Get GitHub Login Redirect URL",
)
async def get_github_url():
    """
    Constructs and returns the GitHub OAuth Authorization Code Flow URL.
    """
    if not settings.github_client_id:
        raise HTTPException(
            status_code=500, detail="GitHub client credentials are not configured."
        )
    auth_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&redirect_uri={settings.github_redirect_uri}"
        f"&scope=read:user%20user:email"
        f"&state=github"
    )
    return {"url": auth_url}


@router.post(
    "/callback",
    response_model=UserResponse,
    summary="OAuth Code Exchange Callback",
    description=(
        "Exchanges a temporary authorization code from Google or GitHub "
        "for a user profile, saves/updates the user record, and issues "
        "a custom JWT session token stored in an HttpOnly cookie."
    ),
)
async def oauth_callback(
    payload: CallbackRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    code = payload.code
    provider = payload.provider.lower()

    email = None
    provider_id = None
    name = ""
    avatar_url = ""

    async with httpx.AsyncClient() as client:
        if provider == "google":
            # 1. Exchange authorization code for access token
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "code": code,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Google token exchange failed: {token_resp.text}",
                )
            tokens = token_resp.json()
            access_token = tokens.get("access_token")

            # 2. Fetch user profile
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail="Failed to retrieve Google user profile.",
                )
            user_profile = userinfo_resp.json()

            email = user_profile.get("email")
            provider_id = user_profile.get("sub")
            name = user_profile.get("name", "")
            avatar_url = user_profile.get("picture", "")

        elif provider == "github":
            # 1. Exchange authorization code for access token
            token_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": settings.github_redirect_uri,
                },
            )
            if token_resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"GitHub token exchange failed: {token_resp.text}",
                )
            tokens = token_resp.json()
            access_token = tokens.get("access_token")
            if not access_token:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "GitHub token exchange did not return access_token: "
                        f"{tokens}"
                    ),
                )

            # 2. Fetch user profile
            profile_resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "User-Agent": "CareerKinetic-FastAPI-Server",
                },
            )
            if profile_resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail="Failed to retrieve GitHub user profile.",
                )
            user_profile = profile_resp.json()

            email = user_profile.get("email")
            provider_id = user_profile.get("id")
            name = user_profile.get("name") or user_profile.get("login", "")
            avatar_url = user_profile.get("avatar_url", "")

            # 3. Fetch primary email if it was private/not returned
            if not email:
                emails_resp = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "User-Agent": "CareerKinetic-FastAPI-Server",
                    },
                )
                if emails_resp.status_code == 200:
                    emails_list = emails_resp.json()
                    for email_obj in emails_list:
                        if email_obj.get("primary") and email_obj.get("verified"):
                            email = email_obj.get("email")
                            break
                    # If no verified primary, fallback to first email
                    if not email and emails_list:
                        email = emails_list[0].get("email")

        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported OAuth provider: {provider}"
            )

    # Validate results
    if not email:
        raise HTTPException(
            status_code=400,
            detail="Could not retrieve email address from the OAuth provider.",
        )
    if not provider_id:
        raise HTTPException(
            status_code=400,
            detail="Could not retrieve unique user ID from the OAuth provider.",
        )

    # Sync User in local Postgres DB
    stmt = select(User).where(User.email == email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user:
        # User exists: update profile data if it is empty/needs merging
        if not user.profile_data:
            user.profile_data = {}

        if "fullName" not in user.profile_data or not user.profile_data["fullName"]:
            user.profile_data["fullName"] = name
        if "profilePic" not in user.profile_data or not user.profile_data["profilePic"]:
            user.profile_data["profilePic"] = avatar_url

        user.profile_data["provider"] = provider
        user.profile_data["provider_id"] = str(provider_id)
        user.profile_data["isEmailVerified"] = True
        user.auth_provider = provider

        db.add(user)
    else:
        # First-time OAuth login: create new user
        new_uuid = uuid.uuid4()
        profile_data = {
            "fullName": name,
            "profilePic": avatar_url,
            "provider": provider,
            "provider_id": str(provider_id),
            "isEmailVerified": True,
        }
        user = User(
            id=new_uuid,
            email=email,
            role="user",
            profile_data=profile_data,
            auth_provider=provider,
            failed_login_streak=0,
            password_changes_today=0,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    # Issue Custom JWT and set in HttpOnly cookie
    jwt_token = create_access_token(
        user_id=str(user.id), email=user.email, role=user.role
    )

    # Secure cookies on production, allow HTTP on localhost
    is_prod = settings.env == "prod"
    response.set_cookie(
        key="access_token",
        value=jwt_token,
        httponly=True,
        max_age=settings.jwt_expire_minutes * 60,
        expires=settings.jwt_expire_minutes * 60,
        samesite="lax",
        secure=is_prod,
    )

    return user


@router.post(
    "/logout",
    summary="Clear Session Cookie",
    description="Logs the user out by deleting the HttpOnly cookie.",
)
async def logout(response: Response):
    is_prod = settings.env == "prod"
    response.delete_cookie(
        key="access_token",
        httponly=True,
        samesite="lax",
        secure=is_prod,
    )
    return {"status": "logged_out"}


@router.put(
    "/profile",
    response_model=UserResponse,
    summary="Update User Profile JSONB",
    description="Updates the profile JSONB details for the currently logged in user.",
)
async def update_profile(
    payload: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    current_user.profile_data = payload.profile_data
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user


# Deprecated Supabase Sync endpoint
@router.post(
    "/sync",
    response_model=UserResponse,
    summary="Sync Supabase user (DEPRECATED)",
    deprecated=True,
)
async def sync_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    raise HTTPException(
        status_code=400,
        detail="This endpoint is deprecated. Use /api/auth/callback instead.",
    )

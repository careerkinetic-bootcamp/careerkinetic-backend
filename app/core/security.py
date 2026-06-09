import jwt

from app.core.config import settings


def verify_supabase_token(token: str) -> dict:
    """
    Decode and verify a Supabase-issued JWT.

    Supabase signs tokens with HS256 using the project's JWT secret.
    The 'aud' claim is set to 'authenticated' for logged-in users.
    """
    payload = jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
    )
    return payload

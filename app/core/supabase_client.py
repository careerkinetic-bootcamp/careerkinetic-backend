from supabase import Client, create_client

from app.core.config import settings


def get_supabase_admin() -> Client:
    """
    Returns a Supabase client authenticated with the service-role key.

    This key bypasses Row Level Security and should only be used
    for admin operations on the server side. Never expose it to
    the frontend.
    """
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

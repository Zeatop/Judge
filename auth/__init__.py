# auth/__init__.py
"""Module d'authentification OAuth2 pour Judge AI."""

from auth.router import router as auth_router
from auth.models import init_db
from auth.jwt import get_current_user_id, get_optional_user_id
from auth.admin import get_admin_user

__all__ = ["auth_router", "init_db", "get_current_user_id", "get_optional_user_id", "get_admin_user"]
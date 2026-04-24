# auth/jwt.py
"""
Utilitaires JWT : création, vérification, helpers cookie.

Ordre de lecture du token :
  1. Cookie HttpOnly `judge_token`  ← prioritaire (sécurisé)
  2. Header Authorization: Bearer   ← fallback (compatibilité API/scripts)
"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth.config import (
    AUTH_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
    COOKIE_NAME,
    COOKIE_SECURE,
    COOKIE_SAMESITE,
    COOKIE_DOMAIN,
    COOKIE_MAX_AGE,
)

security = HTTPBearer(auto_error=False)


# ── Token creation ───────────────────────────────────────────────────

def create_access_token(user_id: str, email: str | None = None) -> str:
    """Crée un JWT signé pour un utilisateur authentifié."""
    payload = {
        "sub": user_id,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, AUTH_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Décode et valide un JWT. Raise HTTPException si invalide ou expiré."""
    try:
        return jwt.decode(token, AUTH_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expiré.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.")


# ── Cookie helpers ────────────────────────────────────────────────────

def set_auth_cookie(response: Response, token: str) -> None:
    """Pose le cookie HttpOnly sur la réponse."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=COOKIE_MAX_AGE,
        domain=COOKIE_DOMAIN or None,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Supprime le cookie d'auth."""
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        domain=COOKIE_DOMAIN or None,
        path="/",
    )


# ── Token extraction ──────────────────────────────────────────────────

def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    """
    Extrait le JWT depuis :
      1. Cookie HttpOnly (prioritaire)
      2. Header Authorization: Bearer (fallback)
    """
    cookie_token = request.cookies.get(COOKIE_NAME)
    if cookie_token:
        return cookie_token
    if credentials:
        return credentials.credentials
    return None


# ── FastAPI dependencies ──────────────────────────────────────────────

def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """
    Dependency FastAPI : extrait le user_id depuis le cookie ou Bearer.
    Raise 401 si absent ou invalide.
    """
    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'authentification manquant.",
        )
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide : user_id manquant.",
        )
    return user_id


def get_optional_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    """
    Dependency FastAPI : retourne le user_id ou None si pas de token.
    Pour les endpoints accessibles en guest ET authentifié.
    """
    token = _extract_token(request, credentials)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        return payload.get("sub")
    except HTTPException:
        return None
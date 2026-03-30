# auth/jwt_utils.py
"""
Utilitaires JWT : création et vérification des tokens.
"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth.config import AUTH_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRATION_HOURS

security = HTTPBearer(auto_error=False)


def create_access_token(user_id: str, email: str | None = None) -> str:
    """Crée un JWT pour un utilisateur authentifié."""
    payload = {
        "sub": user_id,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, AUTH_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Décode et valide un JWT. Raise HTTPException si invalide."""
    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expiré.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide.",
        )


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """
    Dependency FastAPI : extrait le user_id du JWT Bearer token.
    Usage : @app.get("/protected", dependencies=[Depends(get_current_user_id)])
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'authentification manquant.",
        )
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide : user_id manquant.",
        )
    return user_id


def get_optional_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    """
    Dependency FastAPI : comme get_current_user_id mais retourne None si pas de token.
    Utile pour les endpoints accessibles en mode guest ET authentifié.
    """
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        return payload.get("sub")
    except HTTPException:
        return None
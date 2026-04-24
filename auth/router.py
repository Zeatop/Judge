# auth/router.py
"""
Router FastAPI pour l'authentification OAuth2.

Routes :
    GET  /auth/{provider}/login     → Redirige vers le provider OAuth
    GET  /auth/{provider}/callback  → Callback OAuth, pose le cookie HttpOnly, redirige vers le frontend
    GET  /auth/me                   → Retourne les infos du user connecté
    POST /auth/logout               → Supprime le cookie et déconnecte
"""

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from authlib.integrations.starlette_client import OAuth

from auth.config import OAUTH_PROVIDERS, FRONTEND_URL, ADMIN_EMAILS
from auth.models import get_db, User
from auth.jwt import create_access_token, get_current_user_id, set_auth_cookie, clear_auth_cookie
from auth.user_service import get_or_create_user

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Authlib OAuth client ─────────────────────────────────────────────
oauth = OAuth()

for provider_name, conf in OAUTH_PROVIDERS.items():
    if provider_name == "apple":
        continue
    if not conf.get("client_id"):
        continue
    oauth.register(name=provider_name, **conf)


# ── Helpers extraction user par provider ────────────────────────────

def _extract_google_user(token: dict) -> dict:
    userinfo = token.get("userinfo", {})
    return {
        "provider_user_id": userinfo.get("sub", ""),
        "email": userinfo.get("email"),
        "display_name": userinfo.get("name"),
        "avatar_url": userinfo.get("picture"),
    }


def _extract_facebook_user(token: dict) -> dict:
    access_token = token.get("access_token", "")
    resp = httpx.get(
        "https://graph.facebook.com/me",
        params={"fields": "id,name,email,picture.type(large)", "access_token": access_token},
        timeout=10.0,
    )
    if resp.status_code != 200:
        return {"provider_user_id": "", "email": None, "display_name": None, "avatar_url": None}
    data = resp.json()
    return {
        "provider_user_id": data.get("id", ""),
        "email": data.get("email"),
        "display_name": data.get("name"),
        "avatar_url": data.get("picture", {}).get("data", {}).get("url"),
    }


def _extract_discord_user(token: dict) -> dict:
    access_token = token.get("access_token", "")
    resp = httpx.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )
    if resp.status_code != 200:
        return {"provider_user_id": "", "email": None, "display_name": None, "avatar_url": None}
    data = resp.json()
    avatar_hash = data.get("avatar")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{data['id']}/{avatar_hash}.png"
        if avatar_hash else None
    )
    return {
        "provider_user_id": data.get("id", ""),
        "email": data.get("email"),
        "display_name": data.get("global_name") or data.get("username"),
        "avatar_url": avatar_url,
    }


def _extract_apple_user(id_token_payload: dict, user_data: dict | None = None) -> dict:
    display_name = None
    if user_data and isinstance(user_data, dict):
        name_data = user_data.get("name", {})
        if name_data:
            first = name_data.get("firstName", "")
            last = name_data.get("lastName", "")
            display_name = f"{first} {last}".strip() or None
    return {
        "provider_user_id": id_token_payload.get("sub", ""),
        "email": id_token_payload.get("email"),
        "display_name": display_name,
        "avatar_url": None,
    }


USER_EXTRACTORS = {
    "google": _extract_google_user,
    "facebook": _extract_facebook_user,
    "discord": _extract_discord_user,
}

SUPPORTED_PROVIDERS = {"google", "facebook", "apple", "discord"}


# ── Routes ──────────────────────────────────────────────────────────

@router.get("/{provider}/login")
async def oauth_login(provider: str, request: Request):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider non supporté : {provider}")
    if provider == "apple":
        return _apple_login_redirect(request)
    client = getattr(oauth, provider, None)
    if client is None:
        raise HTTPException(status_code=500, detail=f"Provider {provider} non configuré.")
    redirect_uri = f"{os.getenv('API_BASE_URL')}/auth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Callback OAuth :
      1. Récupère le token du provider
      2. Crée/retrouve le user en DB
      3. Émet un JWT et le pose dans un cookie HttpOnly
      4. Redirige vers le frontend (sans token dans l'URL)
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider non supporté : {provider}")

    try:
        if provider == "apple":
            user_info = await _handle_apple_callback(request)
        else:
            client = getattr(oauth, provider)
            token = await client.authorize_access_token(request)
            extractor = USER_EXTRACTORS.get(provider)
            if not extractor:
                raise HTTPException(status_code=500, detail=f"Pas d'extracteur pour {provider}")
            user_info = extractor(token)
            user_info["access_token"] = token.get("access_token")
            user_info["refresh_token"] = token.get("refresh_token")

        if not user_info.get("provider_user_id"):
            raise HTTPException(status_code=400, detail="Impossible de récupérer l'identifiant du provider.")

        user = get_or_create_user(
            db=db,
            provider=provider,
            provider_user_id=user_info["provider_user_id"],
            email=user_info.get("email"),
            display_name=user_info.get("display_name"),
            avatar_url=user_info.get("avatar_url"),
            access_token=user_info.get("access_token"),
            refresh_token=user_info.get("refresh_token"),
        )

        jwt_token = create_access_token(user_id=user.id, email=user.email)

        # Rediriger vers /auth/callback (sans token dans l'URL)
        response = RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?provider={provider}")
        set_auth_cookie(response, jwt_token)
        return response

    except HTTPException:
        raise
    except Exception as e:
        print(f"[AUTH] Erreur callback {provider}: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=auth_failed&provider={provider}"
        )


@router.get("/me")
def get_me(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Retourne les infos de l'utilisateur connecté."""
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")
    providers = [oa.provider for oa in user.oauth_accounts]
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "providers": providers,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "is_admin": bool(user.email and user.email.lower() in ADMIN_EMAILS),
    }


@router.post("/logout")
def logout():
    """Supprime le cookie HttpOnly et déconnecte l'utilisateur."""
    response = JSONResponse(content={"message": "Déconnecté."})
    clear_auth_cookie(response)
    return response


# ── Apple : gestion manuelle ─────────────────────────────────────────

def _apple_login_redirect(request: Request) -> RedirectResponse:
    from auth.config import APPLE_CLIENT_ID
    from urllib.parse import urlencode
    redirect_uri = f"{os.getenv('API_BASE_URL')}/auth/apple/callback"
    params = {
        "response_type": "code",
        "response_mode": "form_post",
        "client_id": APPLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "name email",
        "state": "apple_oauth_state",
    }
    return RedirectResponse(url=f"https://appleid.apple.com/auth/authorize?{urlencode(params)}")


async def _handle_apple_callback(request: Request) -> dict:
    import json
    import jwt as pyjwt
    from auth.apple_auth import generate_apple_client_secret
    from auth.config import APPLE_CLIENT_ID

    form = await request.form()
    code = form.get("code")
    id_token_raw = form.get("id_token")
    user_raw = form.get("user")

    if not code:
        raise HTTPException(status_code=400, detail="Apple: code manquant.")

    client_secret = generate_apple_client_secret()
    redirect_uri = f"{os.getenv('API_BASE_URL')}/auth/apple/callback"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://appleid.apple.com/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": APPLE_CLIENT_ID,
                "client_secret": client_secret,
            },
            timeout=10.0,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Apple: token exchange failed ({resp.status_code})")

    token_data = resp.json()
    id_token = token_data.get("id_token", id_token_raw)
    payload = pyjwt.decode(id_token, options={"verify_signature": False})

    user_data = None
    if user_raw:
        try:
            user_data = json.loads(user_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    user_info = _extract_apple_user(payload, user_data)
    user_info["access_token"] = token_data.get("access_token")
    user_info["refresh_token"] = token_data.get("refresh_token")
    return user_info
# auth/router.py
"""
Router FastAPI pour l'authentification OAuth2.
Routes :
    GET  /auth/{provider}/login     → Redirige vers le provider OAuth
    GET  /auth/{provider}/callback  → Callback après auth, crée/retrouve le user, redirige vers le frontend avec JWT
    GET  /auth/me                   → Retourne les infos du user connecté
    POST /auth/logout               → Placeholder (côté client, supprimer le token suffit)
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from authlib.integrations.starlette_client import OAuth

from auth.config import OAUTH_PROVIDERS, FRONTEND_URL
from auth.models import get_db, User
from auth.jwt import create_access_token, get_current_user_id
from auth.user_service import get_or_create_user

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Authlib OAuth client ────────────────────────────────────────────
oauth = OAuth()

# Enregistrer chaque provider sauf Apple (géré manuellement)
for provider_name, conf in OAUTH_PROVIDERS.items():
    if provider_name == "apple":
        continue
    if not conf.get("client_id"):
        continue  # Skip si pas configuré
    oauth.register(name=provider_name, **conf)


# ── Helpers pour extraire les infos user selon le provider ──────────

def _extract_google_user(token: dict) -> dict:
    """Extrait les infos user depuis le token Google OpenID Connect."""
    userinfo = token.get("userinfo", {})
    return {
        "provider_user_id": userinfo.get("sub", ""),
        "email": userinfo.get("email"),
        "display_name": userinfo.get("name"),
        "avatar_url": userinfo.get("picture"),
    }


def _extract_facebook_user(token: dict) -> dict:
    """Extrait les infos user depuis l'API Facebook Graph."""
    access_token = token.get("access_token", "")
    # Facebook nécessite un appel supplémentaire à /me
    resp = httpx.get(
        "https://graph.facebook.com/me",
        params={
            "fields": "id,name,email,picture.type(large)",
            "access_token": access_token,
        },
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
    """Extrait les infos user depuis l'API Discord."""
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
    avatar_url = None
    if avatar_hash:
        avatar_url = f"https://cdn.discordapp.com/avatars/{data['id']}/{avatar_hash}.png"

    return {
        "provider_user_id": data.get("id", ""),
        "email": data.get("email"),
        "display_name": data.get("global_name") or data.get("username"),
        "avatar_url": avatar_url,
    }


def _extract_apple_user(id_token_payload: dict, user_data: dict | None = None) -> dict:
    """Extrait les infos user depuis le token Apple."""
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
        "avatar_url": None,  # Apple ne fournit pas d'avatar
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
    """Redirige l'utilisateur vers la page de login du provider OAuth."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider non supporté : {provider}")

    if provider == "apple":
        return _apple_login_redirect(request)

    client = getattr(oauth, provider, None)
    if client is None:
        raise HTTPException(status_code=500, detail=f"Provider {provider} non configuré.")

    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Callback OAuth : récupère le token, extrait les infos user,
    crée ou retrouve le user en DB, puis redirige vers le frontend avec un JWT.
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

        # Créer ou retrouver le user en DB
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

        # Émettre notre propre JWT
        jwt_token = create_access_token(user_id=user.id, email=user.email)

        # Rediriger vers le frontend avec le token
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?token={jwt_token}&provider={provider}"
        )

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
    }


@router.post("/logout")
def logout():
    """
    Côté stateless JWT, le logout est géré par le frontend (supprimer le token).
    Cet endpoint existe pour la cohérence de l'API.
    """
    return {"message": "Token invalidé côté client."}


# ── Apple : gestion manuelle (pas de server_metadata standard) ──────

def _apple_login_redirect(request: Request) -> RedirectResponse:
    """Construit manuellement l'URL d'autorisation Apple."""
    from auth.config import APPLE_CLIENT_ID
    from urllib.parse import urlencode

    redirect_uri = str(request.url_for("oauth_callback", provider="apple"))

    params = {
        "response_type": "code",
        "response_mode": "form_post",
        "client_id": APPLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "name email",
        "state": "apple_oauth_state",  # TODO: générer un state aléatoire + le stocker en session
    }
    url = f"https://appleid.apple.com/auth/authorize?{urlencode(params)}"
    return RedirectResponse(url=url)


async def _handle_apple_callback(request: Request) -> dict:
    """
    Traite le callback Apple (form_post).
    Apple envoie le code + id_token en POST form data.
    On échange le code contre un token, puis on décode l'id_token.
    """
    import json
    import jwt as pyjwt
    from auth.apple_auth import generate_apple_client_secret
    from auth.config import APPLE_CLIENT_ID

    form = await request.form()
    code = form.get("code")
    id_token_raw = form.get("id_token")
    user_raw = form.get("user")  # Seulement au premier login

    if not code:
        raise HTTPException(status_code=400, detail="Apple: code manquant.")

    # Échanger le code contre un token
    client_secret = generate_apple_client_secret()
    redirect_uri = str(request.url_for("oauth_callback", provider="apple"))

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

    # Décoder l'id_token (sans vérification de signature en V1 — à renforcer en prod)
    # En prod : vérifier avec les clés publiques Apple depuis https://appleid.apple.com/auth/keys
    payload = pyjwt.decode(id_token, options={"verify_signature": False})

    # Données user (seulement fournies au premier login)
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
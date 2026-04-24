# auth/config.py
"""
Configuration centralisée pour l'authentification OAuth2 + JWT + cookies.

Variables d'environnement requises :
    AUTH_SECRET_KEY=<random-string-64-chars-minimum>
    FRONTEND_URL=http://localhost:5173
    API_BASE_URL=https://api.judgeai.app   ← détermine COOKIE_SECURE automatiquement

    # Google
    GOOGLE_JUDGE_CLIENT_ID=xxx
    GOOGLE_JUDGE_CLIENT_SECRET=xxx

    # Discord
    DISCORD_JUDGE_CLIENT_ID=xxx
    DISCORD_JUDGE_CLIENT_SECRET=xxx

    # Cookie (optionnel)
    COOKIE_DOMAIN=.judgeai.app   ← à définir en prod pour couvrir les sous-domaines
"""

import os

# ── JWT ─────────────────────────────────────────────────────────────
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_use_openssl_rand_hex_64")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 30  # 30 jours

# ── Frontend ────────────────────────────────────────────────────────
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# ── Cookie ──────────────────────────────────────────────────────────
COOKIE_NAME = "judge_token"
# Secure=True uniquement si l'API tourne en HTTPS (prod).
# En dev (http://localhost), Secure=False pour que le cookie soit envoyé.
COOKIE_SECURE: bool = API_BASE_URL.startswith("https")
COOKIE_SAMESITE: str = "lax"
# Domain vide = cookie limité à l'hôte exact.
# En prod avec sous-domaines (judgeai.app / api.judgeai.app), mettre ".judgeai.app".
COOKIE_DOMAIN: str = os.getenv("COOKIE_DOMAIN", "")
COOKIE_MAX_AGE: int = JWT_EXPIRATION_HOURS * 3600  # secondes

# ── OAuth2 Providers ────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_JUDGE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_JUDGE_CLIENT_SECRET", "")

FACEBOOK_CLIENT_ID = os.getenv("FACEBOOK_CLIENT_ID", "")
FACEBOOK_CLIENT_SECRET = os.getenv("FACEBOOK_CLIENT_SECRET", "")

APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "")
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")
APPLE_KEY_PATH = os.getenv("APPLE_KEY_PATH", "./AuthKey.p8")

DISCORD_CLIENT_ID = os.getenv("DISCORD_JUDGE_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_JUDGE_CLIENT_SECRET", "")

OAUTH_PROVIDERS = {
    "google": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile"},
    },
    "facebook": {
        "client_id": FACEBOOK_CLIENT_ID,
        "client_secret": FACEBOOK_CLIENT_SECRET,
        "authorize_url": "https://www.facebook.com/v19.0/dialog/oauth",
        "access_token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
        "userinfo_endpoint": "https://graph.facebook.com/me?fields=id,name,email,picture",
        "client_kwargs": {"scope": "email public_profile"},
    },
    "discord": {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "authorize_url": "https://discord.com/api/oauth2/authorize",
        "access_token_url": "https://discord.com/api/oauth2/token",
        "userinfo_endpoint": "https://discord.com/api/users/@me",
        "client_kwargs": {"scope": "identify email"},
    },
    "apple": {
        "client_id": APPLE_CLIENT_ID,
        "client_secret": "",
        "authorize_url": "https://appleid.apple.com/auth/authorize",
        "access_token_url": "https://appleid.apple.com/auth/token",
        "client_kwargs": {"scope": "name email", "response_mode": "form_post"},
    },
}

ADMIN_EMAILS: set[str] = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}
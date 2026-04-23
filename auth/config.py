# auth/config.py
"""
Configuration centralisée pour l'authentification OAuth2 + JWT.

Variables d'environnement requises (à mettre dans .env ou exporter) :
    # JWT
    AUTH_SECRET_KEY=<random-string-de-64-chars-minimum>
    FRONTEND_URL=http://localhost:5173

    # Google
    GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
    GOOGLE_CLIENT_SECRET=xxx

    # Facebook
    FACEBOOK_CLIENT_ID=xxx
    FACEBOOK_CLIENT_SECRET=xxx

    # Apple (plus complexe — nécessite un .p8 key file)
    APPLE_CLIENT_ID=com.example.app          # = Services ID
    APPLE_TEAM_ID=1A234BFK46
    APPLE_KEY_ID=1ABC6523AA
    APPLE_KEY_PATH=./AuthKey.p8              # chemin vers le fichier .p8

    # Discord
    DISCORD_CLIENT_ID=xxx
    DISCORD_CLIENT_SECRET=xxx
"""

import os

# ── JWT ─────────────────────────────────────────────────────────────
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_use_openssl_rand_hex_64")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7 jours

# ── Frontend ────────────────────────────────────────────────────────
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# ── Google OAuth2 ──────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_JUDGE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_JUDGE_CLIENT_SECRET", "")

# ── Facebook OAuth2 ────────────────────────────────────────────────
FACEBOOK_CLIENT_ID = os.getenv("FACEBOOK_CLIENT_ID", "")
FACEBOOK_CLIENT_SECRET = os.getenv("FACEBOOK_CLIENT_SECRET", "")

# ── Apple Sign In ──────────────────────────────────────────────────
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "")
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")
APPLE_KEY_PATH = os.getenv("APPLE_KEY_PATH", "./AuthKey.p8")

# ── Discord OAuth2 ─────────────────────────────────────────────────
DISCORD_CLIENT_ID = os.getenv("DISCORD_JUDGE_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_JUDGE_CLIENT_SECRET", "")


# ── Providers registry (pour Authlib) ──────────────────────────────
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
    # Apple est géré différemment (pas de server_metadata standard côté Authlib web)
    "apple": {
        "client_id": APPLE_CLIENT_ID,
        "client_secret": "",  # Généré dynamiquement via JWT signé avec .p8
        "authorize_url": "https://appleid.apple.com/auth/authorize",
        "access_token_url": "https://appleid.apple.com/auth/token",
        "client_kwargs": {
            "scope": "name email",
            "response_mode": "form_post",
        },
    },
}

ADMIN_EMAILS: set[str] = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}
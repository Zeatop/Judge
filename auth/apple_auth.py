# auth/apple_utils.py
"""
Utilitaires spécifiques à Sign in with Apple.
Apple ne fonctionne pas comme les autres providers : le client_secret est un JWT
signé avec la clé privée .p8 fournie par Apple Developer.
"""

import time
import jwt
from auth.config import APPLE_CLIENT_ID, APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_KEY_PATH


def generate_apple_client_secret() -> str:
    """
    Génère le client_secret JWT pour Apple.
    Valide 6 mois max (Apple impose cette limite).
    Nécessite le fichier .p8 téléchargé depuis Apple Developer.
    """
    now = int(time.time())

    headers = {
        "alg": "ES256",
        "kid": APPLE_KEY_ID,
    }

    payload = {
        "iss": APPLE_TEAM_ID,
        "iat": now,
        "exp": now + (86400 * 180),  # 180 jours
        "aud": "https://appleid.apple.com",
        "sub": APPLE_CLIENT_ID,
    }

    with open(APPLE_KEY_PATH, "r") as f:
        private_key = f.read()

    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
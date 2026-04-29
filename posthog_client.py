# posthog_client.py
"""
Client PostHog singleton pour le backend.
Si POSTHOG_API_KEY n'est pas défini, get_posthog() retourne None et tous les
appels capture/capture_exception sont no-op (pratique en dev).
"""

import os
from posthog import Posthog

_client: Posthog | None = None
_initialized = False


def get_posthog() -> Posthog | None:
    global _client, _initialized
    if _initialized:
        return _client

    _initialized = True
    api_key = os.getenv("POSTHOG_API_KEY", "").strip()
    if not api_key:
        print("[POSTHOG] POSTHOG_API_KEY non défini — analytics désactivés")
        return None

    host = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com")
    _client = Posthog(
        project_api_key=api_key,
        host=host,
        # Production : envoi async, pas de logs verbeux
        debug=False,
    )
    print(f"[POSTHOG] Initialisé sur {host}")
    return _client


def shutdown_posthog() -> None:
    """Vide la queue d'événements avant l'arrêt du process."""
    global _client
    if _client is not None:
        try:
            _client.shutdown()
            print("[POSTHOG] Queue vidée")
        except Exception as e:
            print(f"[POSTHOG] Erreur shutdown: {e}")
# chat/rate_limit.py
"""
Rate limiting par crédits journaliers, stockés dans MongoDB.

Fenêtre journalière basée sur Europe/Paris : le compteur d'un sujet
(user ou IP) est identifié par (subject, jour). À minuit Paris, la clé
de jour change, donc le compteur repart à zéro sans tâche planifiée.

Un index TTL nettoie passivement les vieux documents.

Politique fail-closed : si MongoDB est indisponible, on REFUSE la requête
(503) plutôt que de laisser passer. Le rate limit protège la facture API ;
une panne Mongo ne doit jamais rouvrir l'accès illimité au LLM.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, status
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from chat.mongo import get_db

PARIS = ZoneInfo("Europe/Paris")

# ── Quotas journaliers ──────────────────────────────────────────────
LIMIT_AUTHENTICATED = 10
LIMIT_GUEST = 5            # par IP, non authentifié
QUOTA_DOC_TTL_DAYS = 2     # purge des vieux compteurs


def _today_key() -> str:
    """Clé de fenêtre : date courante en heure de Paris (YYYY-MM-DD)."""
    return datetime.now(PARIS).strftime("%Y-%m-%d")


def _seconds_until_paris_midnight() -> int:
    """Secondes restantes avant le prochain minuit Paris (pour Retry-After)."""
    now = datetime.now(PARIS)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int((tomorrow - now).total_seconds())


def get_client_ip(request: Request) -> str:
    """
    IP du client derrière Traefik (k3s).

    Chaîne validée : Client → Traefik (externalTrafficPolicy=Local, écrase le
    XFF entrant) → service judge:8000. Un seul proxy, donc le premier élément
    du X-Forwarded-For est l'IP réelle du client et n'est pas spoofable.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

async def check_and_consume_quota(
    user_id: str | None,
    request: Request,
) -> int:
    """
    Vérifie le quota ET consomme un crédit de façon atomique.

    À appeler AVANT tout appel coûteux (Scryfall, LLM) et après la
    validation du modèle (pour ne pas consommer un crédit sur une 400).

    Retourne le nombre de crédits restants après consommation (>= 0),
    utile pour exposer un compteur au frontend.

    Raise :
      - 429 si le quota journalier est dépassé (avec Retry-After).
      - 503 si MongoDB est indisponible (fail-closed).
    """
    db = get_db()
    if db is None:
        # Fail-closed : pas de Mongo = pas de garde-fou = on refuse.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporairement indisponible. Réessaie dans un instant.",
        )

    if user_id:
        subject = f"user:{user_id}"
        limit = LIMIT_AUTHENTICATED
    else:
        subject = f"ip:{get_client_ip(request)}"
        limit = LIMIT_GUEST

    day = _today_key()
    key = f"{subject}:{day}"
    now = datetime.now(PARIS)

    # Incrément atomique + upsert, lecture du count APRÈS incrément.
    try:
        doc = await db.rate_limits.find_one_and_update(
            {"_id": key},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {
                    "subject": subject,
                    "day": day,
                    "expires_at": now + timedelta(days=QUOTA_DOC_TTL_DAYS),
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError as e:
        # Erreur Mongo en cours de route : fail-closed également.
        print(f"[RATE_LIMIT] Erreur MongoDB ({type(e).__name__}) — requête refusée")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporairement indisponible. Réessaie dans un instant.",
        )

    count = doc["count"]

    if count > limit:
        # On a incrémenté au-delà de la limite : on annule l'incrément pour
        # que le compteur ne dérive pas indéfiniment pendant le spam de refus.
        try:
            await db.rate_limits.update_one({"_id": key}, {"$inc": {"count": -1}})
        except PyMongoError:
            # Le décrément a échoué : pas grave, le TTL purgera. On bloque quand même.
            pass

        retry = _seconds_until_paris_midnight()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Limite de {limit} questions par jour atteinte. "
                f"Tes crédits se réinitialisent à minuit."
            ),
            headers={"Retry-After": str(retry)},
        )

    return max(0, limit - count)
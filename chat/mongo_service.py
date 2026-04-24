# chat/mongo_service.py
"""
Service CRUD pour les chats et messages.
Toutes les opérations MongoDB sont async.

Supporte deux modes de propriété :
  - Utilisateur authentifié : user_id (str)
  - Invité                  : session_id (UUID généré côté frontend, stocké en localStorage)

Les chats invités sont auto-supprimés après GUEST_CHAT_TTL_DAYS jours via un index TTL MongoDB.
Pour activer le TTL, s'assurer que connect_mongo() crée l'index :
    await db.chats.create_index("guest_expires_at", expireAfterSeconds=0)
"""

from datetime import datetime, timezone, timedelta
from bson import ObjectId
from chat.mongo import get_db

GUEST_CHAT_TTL_DAYS = 30


# ── Helpers ─────────────────────────────────────────────────────────

def _serialize_doc(doc: dict) -> dict:
    """Convertit un document MongoDB en dict sérialisable (ObjectId → str)."""
    if doc is None:
        return None
    doc["id"] = str(doc.pop("_id"))
    return doc


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Chats ───────────────────────────────────────────────────────────

async def create_chat(
    game_id: str,
    title: str = "Nouveau chat",
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    """
    Crée un nouveau chat.
    Exactement un de user_id ou session_id doit être fourni.
    Les chats invités reçoivent un champ guest_expires_at pour le TTL MongoDB.
    """
    if not user_id and not session_id:
        raise ValueError("create_chat requiert user_id ou session_id")

    db = get_db()
    if db is None:
        raise RuntimeError("MongoDB non disponible")

    now = _now()
    doc = {
        "game_id": game_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
    }

    if user_id:
        doc["user_id"] = user_id
    else:
        doc["session_id"] = session_id
        doc["user_id"] = None
        doc["guest_expires_at"] = now + timedelta(days=GUEST_CHAT_TTL_DAYS)

    result = await db.chats.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_doc(doc)


async def get_user_chats(user_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
    """Retourne les chats d'un user authentifié, triés par updated_at desc."""
    db = get_db()
    cursor = (
        db.chats.find({"user_id": user_id})
        .sort("updated_at", -1)
        .skip(skip)
        .limit(limit)
    )
    chats = []
    async for doc in cursor:
        chats.append(_serialize_doc(doc))
    return chats


async def get_guest_chats(session_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
    """Retourne les chats d'un invité via son session_id, triés par updated_at desc."""
    db = get_db()
    cursor = (
        db.chats.find({"session_id": session_id})
        .sort("updated_at", -1)
        .skip(skip)
        .limit(limit)
    )
    chats = []
    async for doc in cursor:
        chats.append(_serialize_doc(doc))
    return chats


async def get_chat(chat_id: str, user_id: str) -> dict | None:
    """Retourne un chat par son ID pour un user authentifié."""
    db = get_db()
    doc = await db.chats.find_one({"_id": ObjectId(chat_id), "user_id": user_id})
    return _serialize_doc(doc) if doc else None


async def get_guest_chat(chat_id: str, session_id: str) -> dict | None:
    """Retourne un chat par son ID pour un invité (vérifie session_id)."""
    db = get_db()
    doc = await db.chats.find_one({"_id": ObjectId(chat_id), "session_id": session_id})
    return _serialize_doc(doc) if doc else None


async def update_chat(chat_id: str, user_id: str, **fields) -> dict | None:
    """Met à jour un chat (title, game_id, etc.) pour un user authentifié."""
    db = get_db()
    fields["updated_at"] = _now()
    result = await db.chats.find_one_and_update(
        {"_id": ObjectId(chat_id), "user_id": user_id},
        {"$set": fields},
        return_document=True,
    )
    return _serialize_doc(result) if result else None


async def delete_chat(chat_id: str, user_id: str | None = None, session_id: str | None = None) -> bool:
    """
    Supprime un chat et tous ses messages.
    Accepte user_id (authentifié) ou session_id (invité) pour vérifier la propriété.
    """
    db = get_db()
    oid = ObjectId(chat_id)

    if user_id:
        query = {"_id": oid, "user_id": user_id}
    elif session_id:
        query = {"_id": oid, "session_id": session_id}
    else:
        return False

    chat = await db.chats.find_one(query)
    if not chat:
        return False
    await db.messages.delete_many({"chat_id": chat_id})
    await db.chats.delete_one({"_id": oid})
    return True


async def touch_chat(chat_id: str):
    """Met à jour le updated_at d'un chat (après un nouveau message)."""
    db = get_db()
    await db.chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"updated_at": _now()}},
    )


async def migrate_guest_chats(session_id: str, user_id: str) -> int:
    """
    Réassigne tous les chats d'un invité à un user authentifié.
    Appelé à l'inscription ou à la connexion si session_id est fourni.
    Retourne le nombre de chats migrés.
    """
    db = get_db()
    result = await db.chats.update_many(
        {"session_id": session_id},
        {
            "$set": {"user_id": user_id},
            "$unset": {"session_id": "", "guest_expires_at": ""},
        },
    )
    migrated = result.modified_count
    if migrated:
        print(f"[CHAT] {migrated} chat(s) migrés de session {session_id[:8]}... → user {user_id}")
    return migrated


# ── Messages ────────────────────────────────────────────────────────

async def add_message(
    chat_id: str,
    role: str,
    content: str,
    cards: list[dict] | None = None,
    chunks_used: int | None = None,
) -> dict:
    """Ajoute un message à un chat (user ou invité)."""
    db = get_db()
    doc = {
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "created_at": _now(),
    }
    if cards is not None:
        doc["cards"] = cards
    if chunks_used is not None:
        doc["chunks_used"] = chunks_used

    result = await db.messages.insert_one(doc)
    doc["_id"] = result.inserted_id

    await touch_chat(chat_id)

    return _serialize_doc(doc)


async def get_messages(chat_id: str, limit: int = 200) -> list[dict]:
    """Retourne les messages d'un chat, triés chronologiquement."""
    db = get_db()
    cursor = (
        db.messages.find({"chat_id": chat_id})
        .sort("created_at", 1)
        .limit(limit)
    )
    msgs = []
    async for doc in cursor:
        msgs.append(_serialize_doc(doc))
    return msgs


async def get_recent_exchanges(chat_id: str, n: int = 3) -> list[dict]:
    """
    Retourne les n derniers échanges (paires user/assistant) d'un chat.
    Retourne jusqu'à n*2 messages (n questions + n réponses).
    Fonctionne pour les chats user et invité (pas de vérification de propriété ici).
    """
    db = get_db()
    cursor = (
        db.messages.find({"chat_id": chat_id})
        .sort("created_at", -1)
        .limit(n * 2)
    )
    msgs = []
    async for doc in cursor:
        msgs.append(_serialize_doc(doc))
    msgs.reverse()
    return msgs
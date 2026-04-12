# chat/service.py
"""
Service CRUD pour les chats et messages.
Toutes les opérations MongoDB sont async.
"""

from datetime import datetime, timezone
from bson import ObjectId
from chat.mongo import get_db


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

async def create_chat(user_id: str, game_id: str, title: str = "Nouveau chat") -> dict:
    """Crée un nouveau chat et retourne le document créé."""
    db = get_db()
    now = _now()
    doc = {
        "user_id": user_id,
        "game_id": game_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.chats.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_doc(doc)


async def get_user_chats(user_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
    """Retourne les chats d'un user, triés par updated_at desc."""
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


async def get_chat(chat_id: str, user_id: str) -> dict | None:
    """Retourne un chat par son ID, vérifie que le user est propriétaire."""
    db = get_db()
    doc = await db.chats.find_one({"_id": ObjectId(chat_id), "user_id": user_id})
    return _serialize_doc(doc) if doc else None


async def update_chat(chat_id: str, user_id: str, **fields) -> dict | None:
    """Met à jour un chat (title, game_id, etc.)."""
    db = get_db()
    fields["updated_at"] = _now()
    result = await db.chats.find_one_and_update(
        {"_id": ObjectId(chat_id), "user_id": user_id},
        {"$set": fields},
        return_document=True,
    )
    return _serialize_doc(result) if result else None


async def delete_chat(chat_id: str, user_id: str) -> bool:
    """Supprime un chat et tous ses messages."""
    db = get_db()
    oid = ObjectId(chat_id)
    # Vérifier la propriété
    chat = await db.chats.find_one({"_id": oid, "user_id": user_id})
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


# ── Messages ────────────────────────────────────────────────────────

async def add_message(
    chat_id: str,
    role: str,
    content: str,
    cards: list[dict] | None = None,
    chunks_used: int | None = None,
) -> dict:
    """Ajoute un message à un chat."""
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

    # Mettre à jour le timestamp du chat
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
    msgs.reverse()  # Remettre en ordre chronologique
    return msgs
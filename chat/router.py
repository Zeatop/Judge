# chat/router.py
"""
Router FastAPI pour la gestion des chats et messages.

Routes :
    POST   /chats                → Créer un chat (auth ou invité)
    GET    /chats                → Lister les chats (auth ou invité via ?session_id=)
    GET    /chats/{id}           → Détail d'un chat + messages (auth ou invité)
    PATCH  /chats/{id}           → Renommer un chat (auth uniquement)
    DELETE /chats/{id}           → Supprimer un chat (auth ou invité)

Règle de propriété :
  - Authentifié : user_id extrait du JWT (prioritaire)
  - Invité       : session_id passé en query param ou body
  - Si aucun des deux → 401
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from auth.jwt import get_current_user_id, get_optional_user_id
import chat.mongo_service as chat_service

router = APIRouter(prefix="/chats", tags=["chats"])


# ── Schemas ──────────────────────────────────────────────────────────

class CreateChatRequest(BaseModel):
    game_id: str
    title: str = "Nouveau chat"
    session_id: str | None = None  # Requis si non authentifié


class UpdateChatRequest(BaseModel):
    title: str | None = None
    game_id: str | None = None


class ChatResponse(BaseModel):
    id: str
    user_id: str | None       # None pour les chats invités
    game_id: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    cards: list[dict] | None = None
    chunks_used: int | None = None
    created_at: str


class ChatDetailResponse(BaseModel):
    chat: ChatResponse
    messages: list[MessageResponse]


# ── Helpers ──────────────────────────────────────────────────────────

def _format_chat(chat: dict) -> ChatResponse:
    def _iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return ChatResponse(
        id=chat["id"],
        user_id=chat.get("user_id"),
        game_id=chat["game_id"],
        title=chat["title"],
        created_at=_iso(chat["created_at"]),
        updated_at=_iso(chat["updated_at"]),
    )


def _format_message(msg: dict) -> MessageResponse:
    def _iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return MessageResponse(
        id=msg["id"],
        chat_id=msg["chat_id"],
        role=msg["role"],
        content=msg["content"],
        cards=msg.get("cards"),
        chunks_used=msg.get("chunks_used"),
        created_at=_iso(msg["created_at"]),
    )


def _require_identity(user_id: str | None, session_id: str | None) -> None:
    """Lève une 401 si ni user_id ni session_id ne sont fournis."""
    if not user_id and not session_id:
        raise HTTPException(status_code=401, detail="Authentification ou session_id requis.")


# ── Routes ───────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse, status_code=201)
async def create_chat(
    req: CreateChatRequest,
    user_id: str | None = Depends(get_optional_user_id),
):
    """
    Crée un nouveau chat.
    Authentifié → lié au user_id.
    Invité → fournir session_id dans le body.
    """
    _require_identity(user_id, req.session_id)

    chat = await chat_service.create_chat(
        game_id=req.game_id,
        title=req.title,
        user_id=user_id or None,
        session_id=req.session_id if not user_id else None,
    )
    return _format_chat(chat)


@router.get("", response_model=list[ChatResponse])
async def list_chats(
    session_id: str | None = Query(None, description="Session invité (si non authentifié)"),
    limit: int = 50,
    skip: int = 0,
    user_id: str | None = Depends(get_optional_user_id),
):
    """
    Liste les chats.
    Authentifié → chats du user_id (session_id ignoré).
    Invité → ?session_id=<uuid>.
    """
    _require_identity(user_id, session_id)

    if user_id:
        chats = await chat_service.get_user_chats(user_id, limit=limit, skip=skip)
    else:
        chats = await chat_service.get_guest_chats(session_id, limit=limit, skip=skip)

    return [_format_chat(c) for c in chats]


@router.get("/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(
    chat_id: str,
    session_id: str | None = Query(None, description="Session invité (si non authentifié)"),
    user_id: str | None = Depends(get_optional_user_id),
):
    """Retourne un chat avec tous ses messages."""
    _require_identity(user_id, session_id)

    if user_id:
        chat = await chat_service.get_chat(chat_id, user_id)
    else:
        chat = await chat_service.get_guest_chat(chat_id, session_id)

    if not chat:
        raise HTTPException(status_code=404, detail="Chat non trouvé.")

    messages = await chat_service.get_messages(chat_id)
    return ChatDetailResponse(
        chat=_format_chat(chat),
        messages=[_format_message(m) for m in messages],
    )


@router.patch("/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat_id: str,
    req: UpdateChatRequest,
    user_id: str = Depends(get_current_user_id),  # Auth obligatoire pour renommer
):
    """
    Met à jour un chat (titre, jeu).
    Réservé aux utilisateurs authentifiés.
    """
    fields = {}
    if req.title is not None:
        fields["title"] = req.title
    if req.game_id is not None:
        fields["game_id"] = req.game_id
    if not fields:
        raise HTTPException(status_code=400, detail="Rien à mettre à jour.")

    chat = await chat_service.update_chat(chat_id, user_id, **fields)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat non trouvé.")
    return _format_chat(chat)


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: str,
    session_id: str | None = Query(None, description="Session invité (si non authentifié)"),
    user_id: str | None = Depends(get_optional_user_id),
):
    """Supprime un chat et tous ses messages."""
    _require_identity(user_id, session_id)

    deleted = await chat_service.delete_chat(
        chat_id,
        user_id=user_id or None,
        session_id=session_id if not user_id else None,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat non trouvé.")
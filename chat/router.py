# chat/router.py
"""
Router FastAPI pour la gestion des chats et messages.
Routes :
    POST   /chats                → Créer un chat
    GET    /chats                → Lister les chats de l'utilisateur
    GET    /chats/{id}           → Détail d'un chat + messages
    PATCH  /chats/{id}           → Renommer un chat / changer de jeu
    DELETE /chats/{id}           → Supprimer un chat
    POST   /chats/{id}/messages  → Ajouter un message (sans poser la question RAG)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth.jwt import get_current_user_id
import chat.mongo_service as chat_service

router = APIRouter(prefix="/chats", tags=["chats"])


# ── Schemas ─────────────────────────────────────────────────────────

class CreateChatRequest(BaseModel):
    game_id: str
    title: str = "Nouveau chat"


class UpdateChatRequest(BaseModel):
    title: str | None = None
    game_id: str | None = None


class ChatResponse(BaseModel):
    id: str
    user_id: str
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


# ── Helpers ─────────────────────────────────────────────────────────

def _format_chat(chat: dict) -> ChatResponse:
    return ChatResponse(
        id=chat["id"],
        user_id=chat["user_id"],
        game_id=chat["game_id"],
        title=chat["title"],
        created_at=chat["created_at"].isoformat() if hasattr(chat["created_at"], "isoformat") else str(chat["created_at"]),
        updated_at=chat["updated_at"].isoformat() if hasattr(chat["updated_at"], "isoformat") else str(chat["updated_at"]),
    )


def _format_message(msg: dict) -> MessageResponse:
    return MessageResponse(
        id=msg["id"],
        chat_id=msg["chat_id"],
        role=msg["role"],
        content=msg["content"],
        cards=msg.get("cards"),
        chunks_used=msg.get("chunks_used"),
        created_at=msg["created_at"].isoformat() if hasattr(msg["created_at"], "isoformat") else str(msg["created_at"]),
    )


# ── Routes ──────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse, status_code=201)
async def create_chat(
    req: CreateChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Crée un nouveau chat."""
    chat = await chat_service.create_chat(
        user_id=user_id,
        game_id=req.game_id,
        title=req.title,
    )
    return _format_chat(chat)


@router.get("", response_model=list[ChatResponse])
async def list_chats(
    limit: int = 50,
    skip: int = 0,
    user_id: str = Depends(get_current_user_id),
):
    """Liste les chats de l'utilisateur connecté."""
    chats = await chat_service.get_user_chats(user_id, limit=limit, skip=skip)
    return [_format_chat(c) for c in chats]


@router.get("/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(
    chat_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Retourne un chat avec tous ses messages."""
    chat = await chat_service.get_chat(chat_id, user_id)
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
    user_id: str = Depends(get_current_user_id),
):
    """Met à jour un chat (titre, jeu)."""
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
    user_id: str = Depends(get_current_user_id),
):
    """Supprime un chat et tous ses messages."""
    deleted = await chat_service.delete_chat(chat_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat non trouvé.")
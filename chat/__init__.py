# chat/__init__.py
"""Module de gestion des chats et messages pour Judge AI."""

from chat.router import router as chat_router
from chat.mongo import connect_mongo, close_mongo

__all__ = ["chat_router", "connect_mongo", "close_mongo"]
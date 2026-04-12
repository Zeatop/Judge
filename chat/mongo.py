# chat/mongo.py
"""
Connexion MongoDB Atlas via motor (async driver).
Centralise le client et les collections.

Variable d'environnement requise :
    MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/judgeai?retryWrites=true&w=majority
"""

from logging import config
import os
from motor.motor_asyncio import AsyncIOMotorClient
from chat.mongo_config import MONGO_URI

MONGO_URI = os.getenv("MONGO_URI", MONGO_URI)
DB_NAME = os.getenv("MONGO_DB_NAME", "judgeai")

client: AsyncIOMotorClient = None
db = None


async def connect_mongo():
    """Initialise la connexion MongoDB. À appeler au startup de FastAPI."""
    global client, db
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]

    # Créer les index
    await db.chats.create_index([("user_id", 1), ("updated_at", -1)])
    await db.messages.create_index([("chat_id", 1), ("created_at", 1)])

    print(f"[MONGO] Connecté à {DB_NAME}")


async def close_mongo():
    """Ferme la connexion. À appeler au shutdown de FastAPI."""
    global client
    if client:
        client.close()
        print("[MONGO] Déconnecté")


def get_db():
    """Retourne la base de données courante."""
    return db
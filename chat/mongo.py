import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME = os.getenv("MONGO_DB_NAME", "judgeai")

client: AsyncIOMotorClient = None
db = None


async def connect_mongo():
    """Initialise la connexion MongoDB. Optionnel en dev : si MONGO_URI vide ou échec, l'API tourne en mode sans historique."""
    global client, db
    
    if not MONGO_URI:
        print("[MONGO] MONGO_URI non défini — mode sans historique (dev)")
        return
    
    try:
        client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        db = client[DB_NAME]
        # Tester la connexion
        await db.command("ping")
        # Créer les index
        await db.chats.create_index([("user_id", 1), ("updated_at", -1)])
        await db.messages.create_index([("chat_id", 1), ("created_at", 1)])
        print(f"[MONGO] Connecté à {DB_NAME}")
    except Exception as e:
        print(f"[MONGO] Connexion échouée ({e.__class__.__name__}) — mode sans historique")
        client = None
        db = None


async def close_mongo():
    global client
    if client:
        client.close()
        print("[MONGO] Déconnecté")


def get_db():
    return db
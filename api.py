# api.py
"""
API FastAPI pour le RAG de règles de jeux.
Intègre l'API Scryfall pour récupérer le texte des cartes MTG + rulings via la syntaxe [[card name]].
Supporte Ollama (local) et Claude (API Anthropic) via LLM_PROVIDER.

Usage :
    uvicorn api:app --reload
    → Swagger dispo sur http://localhost:8000/docs
"""

import os
import hashlib
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Depends
from pydantic import BaseModel
from db import vectorstore
from pdfProcessor import PDFProcessor
from llm_provider import get_provider
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

# ── Auth ────────────────────────────────────────────────────────────
from auth import auth_router, init_db as init_auth_db,get_admin_user
from auth.config import AUTH_SECRET_KEY
from auth.jwt import get_optional_user_id
from auth.models import User

# ── Chat ────────────────────────────────────────────────────────────
from chat import chat_router, connect_mongo, close_mongo
from chat.mongo_service import add_message, create_chat, get_recent_exchanges

# ── LLM ────────────────────────────────────────────────────────────

from llm_provider import get_cached_provider
from llm_provider import _PROVIDER_CACHE
from availabale_models import AVAILABLE_MODELS, MODELS_BY_ID, DEFAULT_MODEL_ID

# ── RAG ────────────────────────────────────────────────────────────
from rag_core import (
    GAME_PROMPTS,
    DEFAULT_PROMPT,
    CardInfo,
    extract_and_fetch_cards,
)

# ── App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Board Game Rules RAG",
    description="Pose des questions sur les règles de jeux de société. "
                "Pour MTG, utilise [[nom de carte]] pour inclure le texte Oracle + rulings.",
    version="2.4.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", os.getenv("FRONTEND_URL", "http://192.168.1.159:30090")],  # port Vite par défaut
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,  # Nécessaire pour les cookies de session OAuth
)
# SessionMiddleware requis par Authlib pour stocker le state/code temporaire
app.add_middleware(SessionMiddleware, secret_key=AUTH_SECRET_KEY)

# Monter les routers
app.include_router(auth_router)
app.include_router(chat_router)

# Initialiser la DB users au démarrage
init_auth_db()


# ── Lifecycle (MongoDB) ────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    await connect_mongo()


@app.on_event("shutdown")
async def shutdown():
    await close_mongo()


# ── Dossier d'upload ────────────────────────────────────────────────
UPLOAD_DIR = "./rules/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Schemas ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str
    game_id: str | None = None
    chat_id: str | None = None
    model_id: str | None = None
    k: int = 8
    threshold: float = 1.2

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "I cast [[Unsummon]] targeting my opponent's [[Grizzly Bears]]. "
                                "In response, he sacrifices it. What happens?",
                    "game_id": "mtg",
                    "chat_id": "6651f2a3b1c2d3e4f5a6b7c8",
                    "k": 8,
                    "threshold": 1.2,
                }
            ]
        }
    }


class AskResponse(BaseModel):
    question: str
    game_id: str | None
    answer: str
    chunks_used: int
    cards: list[CardInfo]
    chat_id: str | None = None


class UploadResponse(BaseModel):
    game_id: str
    filename: str
    chunks_indexed: int
    total_chunks: int

# ── Helpers ─────────────────────────────────────────────────────────
def make_chunk_id(game_id: str, index: int, content: str) -> str:
    digest = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"{game_id}_{index}_{digest}"
    


# ── Endpoints ───────────────────────────────────────────────────────
@app.post("/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    user_id: str | None = Depends(get_optional_user_id),
):
    """
    Pose une question sur les règles d'un jeu.
    Pour MTG, utilise [[nom de carte]] pour inclure automatiquement le texte Oracle + rulings.
    Si chat_id est fourni, les 3 derniers échanges sont injectés pour le suivi de conversation.
    Les messages sont automatiquement persistés en MongoDB si l'utilisateur est authentifié.
    """
    # 1. Extraire et fetch les cartes Scryfall (+ rulings)
    clean_question, card_texts, card_infos = extract_and_fetch_cards(req.question)

    # 2. Récupérer l'historique de conversation (avant la recherche RAG pour enrichir la query)
    conversation_history = ""
    recent = []
    if req.chat_id:
        recent = await get_recent_exchanges(req.chat_id, n=3)
        if recent:
            lines = []
            for msg in recent:
                role_label = "User" if msg["role"] == "user" else "Assistant"
                lines.append(f"{role_label}: {msg['content']}")
            conversation_history = "\n".join(lines)

    # 3. Recherche dans ChromaDB
    search_query = clean_question
    if card_texts:
        keywords = []
        for ct in card_texts:
            for kw in [
                "target", "return", "untap", "sacrifice", "counter",
                "destroy", "exile", "draw", "discard", "damage",
                "tap", "creature", "spell", "stack", "resolve",
                "copy", "trigger", "cast", "magecraft", "attack",
                "instant", "sorcery", "ability", "permanent",
            ]:
                if kw in ct.lower():
                    keywords.append(kw)
        if keywords:
            search_query += " " + " ".join(set(keywords))

    search_kwargs = {"k": req.k}
    if req.game_id:
        search_kwargs["filter"] = {"game_id": req.game_id}

    results = vectorstore.similarity_search_with_score(search_query, **search_kwargs)
    relevant = [(doc, score) for doc, score in results if score < req.threshold]

    # 4. Si aucun résultat et qu'on a un historique, relancer avec le contexte enrichi
    if not relevant and recent:
        history_user_texts = " ".join(
            msg["content"] for msg in recent if msg["role"] == "user"
        )
        enriched_query = clean_question + " " + history_user_texts
        results = vectorstore.similarity_search_with_score(enriched_query, **search_kwargs)
        relevant = [(doc, score) for doc, score in results if score < req.threshold]

    # 5. Ne court-circuiter que s'il n'y a NI chunks, NI cartes, NI historique
    if not relevant and not card_texts and not conversation_history:
        return AskResponse(
            question=req.question,
            game_id=req.game_id,
            answer="Aucune règle pertinente trouvée.",
            chunks_used=0,
            cards=[],
            chat_id=req.chat_id,
        )

    # 6. Construire le contexte
    if req.game_id:
        role = GAME_PROMPTS.get(req.game_id, DEFAULT_PROMPT)
    else:
        games_found = [doc.metadata.get("game_id", "") for doc, _ in relevant]
        if games_found:
            top_game = max(set(games_found), key=games_found.count)
            role = GAME_PROMPTS.get(top_game, DEFAULT_PROMPT)
        else:
            role = DEFAULT_PROMPT

    rules_context = "\n\n".join([doc.page_content for doc, _ in relevant])

    cards_context = ""
    if card_texts:
        cards_context = (
            "\n\n=== CARD ORACLE TEXTS & OFFICIAL RULINGS (from Scryfall) ===\n\n"
            + "\n\n".join(card_texts)
        )

    history_block = ""
    if conversation_history:
        history_block = f"""

=== CONVERSATION HISTORY (last exchanges) ===
{conversation_history}
=== END HISTORY ===

Use this history to understand follow-up questions. If the user refers to "it", "that card", "the spell", "this", etc., resolve the reference from the history above. The user's new question is a continuation of this conversation."""

    prompt = f"""{role}
You have THREE sources of information below:
1. RULES: Official game rules from the rulebook.
2. CARD TEXTS: The Oracle text of specific cards mentioned in the question.
3. OFFICIAL RULINGS: Clarifications from Wizards of the Coast on how specific cards work.

INSTRUCTIONS:
- Combine ALL sources to answer: use CARD TEXTS to understand what each card does,
  check OFFICIAL RULINGS for clarifications on interactions, then apply RULES.
- Think step by step:
  a) List the Oracle text of each card involved.
  b) Check if any official rulings clarify the interaction being asked about.
  c) Identify EVERY event that could trigger an ability (casting, copying, entering the battlefield...).
  d) List each triggered ability separately and what causes it.
  e) Apply any "additional trigger" or "double trigger" effects (like Veyran's static ability) to EACH individual trigger.
  f) Count the total explicitly before giving the final answer.
- Do NOT say "not in the rules" if the rules cover the relevant mechanic.
- Do NOT invent or reference rules that are not provided below.
- Cite the exact rule number(s) you used.
- If no rules are provided but conversation history contains enough context to answer, use the history.
{history_block}

Rules:
{rules_context}
{cards_context}

Question: {clean_question}
Answer:"""

    model_id = req.model_id or DEFAULT_MODEL_ID
    if model_id not in MODELS_BY_ID:
        raise HTTPException(status_code=400, detail=f"Modèle inconnu : {model_id}")
    model_cfg = MODELS_BY_ID[model_id]
    llm = get_cached_provider(model_cfg["provider"], model_cfg["model"])

    answer = llm.invoke(prompt)

    # 7. Persister les messages en MongoDB
    response_chat_id = req.chat_id
    if user_id:
        try:
            if not response_chat_id:
                # Créer un nouveau chat
                chat = await create_chat(
                    user_id=user_id,
                    game_id=req.game_id or "unknown",
                    title=req.question[:50],
                )
                response_chat_id = chat["id"]

            # Sauvegarder la question et la réponse
            await add_message(response_chat_id, "user", req.question)
            await add_message(
                response_chat_id,
                "assistant",
                answer,
                cards=[c.model_dump() for c in card_infos],
                chunks_used=len(relevant),
            )
        except Exception as e:
            print(f"[CHAT] Erreur persistance: {e}")

    return AskResponse(
        question=req.question,
        game_id=req.game_id,
        answer=answer,
        chunks_used=len(relevant),
        cards=card_infos,
        chat_id=response_chat_id,
    )


@app.post("/upload", response_model=UploadResponse)
async def upload_rules(
    file: UploadFile = File(..., description="PDF des règles du jeu"),
    game_id: str = Query(..., description="Identifiant du jeu (ex: 'Risk', 'Uno')"),
    lang: str = Query("fr", description="Langue des règles (ex: 'fr', 'en')"),
    _admin: User = Depends(get_admin_user),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

    if not game_id.strip():
        raise HTTPException(status_code=400, detail="game_id ne peut pas être vide.")

    lang = lang.strip().lower()

    game_dir = os.path.join(UPLOAD_DIR, game_id)
    os.makedirs(game_dir, exist_ok=True)
    file_path = os.path.join(game_dir, file.filename)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        processor = PDFProcessor(file_path=file_path, game_id=game_id, lang=lang)
        chunks = processor.process_pdf()
        ids = [make_chunk_id(game_id, i, chunk.page_content) for i, chunk in enumerate(chunks)]
        vectorstore.add_documents(chunks, ids=ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du traitement du PDF : {e}")

    if game_id not in GAME_PROMPTS:
        GAME_PROMPTS[game_id] = f"You are an expert on {game_id} board game rules."

    return UploadResponse(
        game_id=game_id,
        filename=file.filename,
        chunks_indexed=len(chunks),
        total_chunks=vectorstore._collection.count(),
    )


@app.get("/games")
def list_games():
    all_metadata = vectorstore._collection.get()["metadatas"]
    games = set(m.get("game_id", "unknown") for m in all_metadata)
    return {"games": sorted(games)}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "chunks_in_db": vectorstore._collection.count(),
        "default_model": DEFAULT_MODEL_ID,
        "cached_providers": len(_PROVIDER_CACHE),
    }

@app.get("/models")
def list_models():
    """Retourne la liste des modèles LLM disponibles pour l'UI."""
    return {
        "default": DEFAULT_MODEL_ID,
        "models": [
            {k: v for k, v in m.items() if k not in {"provider", "model"}}
            for m in AVAILABLE_MODELS
        ],
    }
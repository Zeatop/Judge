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
import re
import time
import hashlib
import shutil
import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from pydantic import BaseModel
from db import vectorstore
from pdfProcessor import PDFProcessor
from llm_provider import get_provider
from fastapi.middleware.cors import CORSMiddleware

# ── App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Board Game Rules RAG",
    description="Pose des questions sur les règles de jeux de société. "
                "Pour MTG, utilise [[nom de carte]] pour inclure le texte Oracle + rulings.",
    version="2.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # port Vite par défaut
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── LLM ─────────────────────────────────────────────────────────────
from var import LLM_MODEL
llm_kwargs = {}
if LLM_MODEL:
    llm_kwargs["model"] = LLM_MODEL

llm = get_provider(**llm_kwargs)

# ── Dossier d'upload ────────────────────────────────────────────────
UPLOAD_DIR = "./rules/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Prompts par jeu ─────────────────────────────────────────────────
GAME_PROMPTS = {
    "mtg": "You are a strict Magic: The Gathering judge.",
    "Catan": "You are an expert on Catan board game rules.",
    "Monopoly": "You are an expert on Monopoly board game rules.",
}
DEFAULT_PROMPT = "You are a board game rules expert."

# ── Scryfall ────────────────────────────────────────────────────────
SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"
SCRYFALL_DELAY = 0.1  # 100ms entre chaque requête (respect des rate limits)
CARD_PATTERN = re.compile(r"\[\[(.+?)\]\]")

SCRYFALL_HEADERS = {
    "User-Agent": "BoardGameRAG/2.1",
    "Accept": "application/json",
}

# ── Schemas ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str
    game_id: str | None = None
    k: int = 8
    threshold: float = 1.2

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "I cast [[Unsummon]] targeting my opponent's [[Grizzly Bears]]. "
                                "In response, he sacrifices it. What happens?",
                    "game_id": "mtg",
                    "k": 8,
                    "threshold": 1.2,
                }
            ]
        }
    }


class CardInfo(BaseModel):
    """Infos d'une carte MTG pour le frontend."""
    name: str
    mana_cost: str
    type_line: str
    oracle_text: str
    image_url: str | None = None
    scryfall_url: str | None = None
    rulings: list[str] = []


class AskResponse(BaseModel):
    question: str
    game_id: str | None
    answer: str
    chunks_used: int
    cards: list[CardInfo]


class UploadResponse(BaseModel):
    game_id: str
    filename: str
    chunks_indexed: int
    total_chunks: int


def fetch_card(card_name: str) -> dict | None:
    """Récupère une carte depuis Scryfall via fuzzy search."""
    try:
        resp = httpx.get(
            SCRYFALL_NAMED_URL,
            params={"fuzzy": card_name},
            headers=SCRYFALL_HEADERS,
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except httpx.RequestError:
        return None


def fetch_rulings(rulings_uri: str) -> list[str]:
    """
    Récupère les rulings officiels d'une carte depuis Scryfall.
    Retourne une liste de textes de rulings, ou [] si aucun.
    """
    try:
        time.sleep(SCRYFALL_DELAY)
        resp = httpx.get(
            rulings_uri,
            headers=SCRYFALL_HEADERS,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        rulings = []
        for entry in data.get("data", []):
            comment = entry.get("comment", "").strip()
            if comment:
                rulings.append(comment)
        return rulings
    except httpx.RequestError:
        return []


def format_card_text(card: dict, rulings: list[str] | None = None) -> str:
    """Formate les infos d'une carte + ses rulings pour injection dans le contexte."""
    name = card.get("name", "Unknown")
    mana_cost = card.get("mana_cost", "")
    type_line = card.get("type_line", "")
    oracle_text = card.get("oracle_text", "")
    power = card.get("power")
    toughness = card.get("toughness")
    loyalty = card.get("loyalty")

    # Cartes double-face : concaténer les deux faces
    if not oracle_text and "card_faces" in card:
        faces = card["card_faces"]
        parts = []
        for face in faces:
            face_text = (
                f"{face.get('name', '')} {face.get('mana_cost', '')}\n"
                f"{face.get('type_line', '')}\n"
                f"{face.get('oracle_text', '')}"
            )
            if face.get("power"):
                face_text += f"\n{face['power']}/{face['toughness']}"
            parts.append(face_text)
        text = f"[CARD: {name}]\n" + "\n---\n".join(parts)
    else:
        text = f"[CARD: {name}] {mana_cost}\n{type_line}\n{oracle_text}"
        if power and toughness:
            text += f"\n{power}/{toughness}"
        if loyalty:
            text += f"\nLoyalty: {loyalty}"

    # Ajouter les rulings si disponibles
    if rulings:
        text += "\n\n  OFFICIAL RULINGS:"
        for i, ruling in enumerate(rulings, 1):
            text += f"\n  {i}. {ruling}"

    return text


def extract_and_fetch_cards(question: str) -> tuple[str, list[str], list[CardInfo]]:
    """
    Extrait les [[card name]] de la question, les récupère sur Scryfall
    (avec leurs rulings), et retourne (question nettoyée, textes pour le contexte LLM, infos pour le frontend).
    """
    matches = CARD_PATTERN.findall(question)
    if not matches:
        return question, [], []

    card_texts = []
    card_infos = []
    for card_name in matches:
        card = fetch_card(card_name.strip())
        if card:
            # Récupérer les rulings via rulings_uri
            rulings = []
            rulings_uri = card.get("rulings_uri")
            if rulings_uri:
                rulings = fetch_rulings(rulings_uri)

            card_texts.append(format_card_text(card, rulings))

            # Construire l'objet CardInfo pour le frontend
            # Gestion des cartes double-face pour oracle_text
            oracle = card.get("oracle_text", "")
            if not oracle and "card_faces" in card:
                oracle = "\n---\n".join(
                    face.get("oracle_text", "") for face in card["card_faces"]
                )

            # Image : priorité à la grande image, fallback sur les faces
            image_url = None
            if "image_uris" in card:
                image_url = card["image_uris"].get("large")
            elif "card_faces" in card and card["card_faces"]:
                face_images = card["card_faces"][0].get("image_uris", {})
                image_url = face_images.get("large")

            card_infos.append(CardInfo(
                name=card.get("name", "Unknown"),
                mana_cost=card.get("mana_cost", ""),
                type_line=card.get("type_line", ""),
                oracle_text=oracle,
                image_url=image_url,
                scryfall_url=card.get("scryfall_uri"),
                rulings=rulings,
            ))
        else:
            card_texts.append(f"[CARD NOT FOUND: {card_name}]")
        time.sleep(SCRYFALL_DELAY)

    clean_question = CARD_PATTERN.sub(lambda m: m.group(1), question)
    return clean_question, card_texts, card_infos



# ── Helpers ─────────────────────────────────────────────────────────
def make_chunk_id(game_id: str, index: int, content: str) -> str:
    digest = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"{game_id}_{index}_{digest}"


# ── Endpoints ───────────────────────────────────────────────────────
@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    """
    Pose une question sur les règles d'un jeu.
    Pour MTG, utilise [[nom de carte]] pour inclure automatiquement le texte Oracle + rulings.
    """
    # 1. Extraire et fetch les cartes Scryfall (+ rulings)
    clean_question, card_texts, card_infos = extract_and_fetch_cards(req.question)

    # 2. Recherche dans ChromaDB
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

    if not relevant and not card_texts:
        return AskResponse(
            question=req.question,
            game_id=req.game_id,
            answer="Aucune règle pertinente trouvée.",
            chunks_used=0,
            cards=[],
        )

    # 3. Construire le contexte
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

Rules:
{rules_context}
{cards_context}

Question: {clean_question}
Answer:"""

    answer = llm.invoke(prompt)

    return AskResponse(
        question=req.question,
        game_id=req.game_id,
        answer=answer,
        chunks_used=len(relevant),
        cards=card_infos,
    )


@app.post("/upload", response_model=UploadResponse)
async def upload_rules(
    file: UploadFile = File(..., description="PDF des règles du jeu"),
    game_id: str = Query(..., description="Identifiant du jeu (ex: 'Risk', 'Uno')"),
    lang: str = Query("fr", description="Langue des règles (ex: 'fr', 'en')"),
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
        "llm_provider": repr(llm),
    }
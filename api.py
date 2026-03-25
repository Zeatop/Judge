# api.py
"""
API FastAPI pour le RAG de règles de jeux.
Intègre l'API Scryfall pour récupérer le texte des cartes MTG via la syntaxe [[card name]].
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
from langchain_ollama import OllamaLLM

# ── App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Board Game Rules RAG",
    description="Pose des questions sur les règles de jeux de société. "
                "Pour MTG, utilise [[nom de carte]] pour inclure le texte Oracle.",
    version="1.1.0",
)

# ── LLM (chargé une seule fois au démarrage) ───────────────────────
llm = OllamaLLM(model="mistral:7b", temperature=0.0, num_ctx=4096)

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


def fetch_card(card_name: str) -> dict | None:
    """
    Récupère une carte depuis Scryfall via fuzzy search.
    Retourne un dict avec name, mana_cost, type_line, oracle_text, etc.
    Retourne None si la carte n'est pas trouvée.
    """
    try:
        resp = httpx.get(
            SCRYFALL_NAMED_URL,
            params={"fuzzy": card_name},
            headers={"User-Agent": "BoardGameRAG/1.0", "Accept": "application/json"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except httpx.RequestError:
        return None


def format_card_text(card: dict) -> str:
    """Formate les infos d'une carte pour injection dans le contexte."""
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
        return f"[CARD: {name}]\n" + "\n---\n".join(parts)

    text = f"[CARD: {name}] {mana_cost}\n{type_line}\n{oracle_text}"
    if power and toughness:
        text += f"\n{power}/{toughness}"
    if loyalty:
        text += f"\nLoyalty: {loyalty}"
    return text


def extract_and_fetch_cards(question: str) -> tuple[str, list[str]]:
    """
    Extrait les [[card name]] de la question, les récupère sur Scryfall,
    et retourne (question nettoyée, liste de textes de cartes).
    """
    matches = CARD_PATTERN.findall(question)
    if not matches:
        return question, []

    card_texts = []
    for card_name in matches:
        card = fetch_card(card_name.strip())
        if card:
            card_texts.append(format_card_text(card))
        else:
            card_texts.append(f"[CARD NOT FOUND: {card_name}]")
        time.sleep(SCRYFALL_DELAY)

    # Nettoie la question (retire les [[ ]])
    clean_question = CARD_PATTERN.sub(lambda m: m.group(1), question)
    return clean_question, card_texts


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


class AskResponse(BaseModel):
    question: str
    game_id: str | None
    answer: str
    chunks_used: int
    cards_fetched: list[str]


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
def ask(req: AskRequest):
    """
    Pose une question sur les règles d'un jeu.
    Pour MTG, utilise [[nom de carte]] pour inclure automatiquement le texte Oracle.
    Exemple : "I cast [[Lightning Bolt]] on a [[Tarmogoyf]], does it die?"
    """
    # 1. Extraire et fetch les cartes Scryfall
    clean_question, card_texts = extract_and_fetch_cards(req.question)

    # 2. Recherche dans ChromaDB
    #    On enrichit la requête avec les mots-clés des cartes pour que
    #    ChromaDB remonte les règles pertinentes (targeting, stack, sacrifice...)
    search_query = clean_question
    if card_texts:
        keywords = []
        for ct in card_texts:
            # Extraire les mots-clés mécaniques du texte Oracle
            for kw in ["target", "return", "untap", "sacrifice", "counter",
                        "destroy", "exile", "draw", "discard", "damage",
                        "tap", "creature", "spell", "stack", "resolve"]:
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
            cards_fetched=[],
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

    # Injecter les cartes Scryfall dans le contexte
    cards_context = ""
    if card_texts:
        cards_context = (
            "\n\n=== CARD ORACLE TEXTS (from Scryfall) ===\n\n"
            + "\n\n".join(card_texts)
        )

    prompt = f"""{role}
You have TWO sources of information below:
1. RULES: Official game rules from the rulebook.
2. CARD TEXTS: The Oracle text of specific cards mentioned in the question.

You MUST combine both sources to answer. Use the CARD TEXTS to understand what each card does, then apply the RULES to determine the outcome.
Do NOT say the answer is not in the rules if the rules cover the relevant game mechanic (targeting, stack resolution, sacrifice, etc.), even if the rules do not mention the specific card by name.
Do NOT use any external knowledge beyond what is provided below.
Cite the exact rule number(s) you used.

Rules:
{rules_context}
{cards_context}

Question: {clean_question}
Answer:"""

    answer = llm.invoke(prompt)

    # Noms des cartes fetchées (pour la réponse)
    fetched_names = [
        t.split("\n")[0].replace("[CARD: ", "").replace("]", "").strip()
        for t in card_texts
        if not t.startswith("[CARD NOT FOUND")
    ]

    return AskResponse(
        question=req.question,
        game_id=req.game_id,
        answer=answer,
        chunks_used=len(relevant),
        cards_fetched=fetched_names,
    )


@app.post("/upload", response_model=UploadResponse)
async def upload_rules(
    file: UploadFile = File(..., description="PDF des règles du jeu"),
    game_id: str = Query(..., description="Identifiant du jeu (ex: 'Risk', 'Uno')"),
):
    """Upload un PDF de règles et l'indexe dans ChromaDB."""

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

    if not game_id.strip():
        raise HTTPException(status_code=400, detail="game_id ne peut pas être vide.")

    game_dir = os.path.join(UPLOAD_DIR, game_id)
    os.makedirs(game_dir, exist_ok=True)
    file_path = os.path.join(game_dir, file.filename)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        processor = PDFProcessor(
            file_path=file_path,
            game_id=game_id,
        )
        chunks = processor.process_pdf()

        ids = [
            make_chunk_id(game_id, i, chunk.page_content)
            for i, chunk in enumerate(chunks)
        ]

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
    """Liste les jeux indexés dans ChromaDB."""
    all_metadata = vectorstore._collection.get()["metadatas"]
    games = set(m.get("game_id", "unknown") for m in all_metadata)
    return {"games": sorted(games)}


@app.get("/health")
def health():
    """Vérifie que l'API et ChromaDB fonctionnent."""
    return {
        "status": "ok",
        "chunks_in_db": vectorstore._collection.count(),
    }
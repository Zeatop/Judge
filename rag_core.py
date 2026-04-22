# rag_core.py
"""
Noyau RAG partagé entre l'API et les scripts de benchmark.
Ne dépend QUE de ChromaDB + Scryfall, pas de FastAPI/auth/Mongo.
"""

import re
import time
import httpx
from pydantic import BaseModel
from db import vectorstore

# ── Prompts par jeu ─────────────────────────────────────────────────
GAME_PROMPTS = {
    "mtg": "You are a strict Magic: The Gathering judge.",
    "Catan": "You are an expert on Catan board game rules.",
    "Monopoly": "You are an expert on Monopoly board game rules.",
}
DEFAULT_PROMPT = "You are a board game rules expert."

# ── Scryfall ────────────────────────────────────────────────────────
SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"
SCRYFALL_DELAY = 0.1
CARD_PATTERN = re.compile(r"\[\[(.+?)\]\]")
SCRYFALL_HEADERS = {
    "User-Agent": "BoardGameRAG/2.1",
    "Accept": "application/json",
}


class CardInfo(BaseModel):
    name: str
    mana_cost: str
    type_line: str
    oracle_text: str
    image_url: str | None = None
    scryfall_url: str | None = None
    rulings: list[str] = []


def fetch_card(card_name: str) -> dict | None:
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
    try:
        time.sleep(SCRYFALL_DELAY)
        resp = httpx.get(rulings_uri, headers=SCRYFALL_HEADERS, timeout=10.0)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [e.get("comment", "").strip() for e in data.get("data", []) if e.get("comment", "").strip()]
    except httpx.RequestError:
        return []


def format_card_text(card: dict, rulings: list[str] | None = None) -> str:
    name = card.get("name", "Unknown")
    mana_cost = card.get("mana_cost", "")
    type_line = card.get("type_line", "")
    oracle_text = card.get("oracle_text", "")
    power = card.get("power")
    toughness = card.get("toughness")
    loyalty = card.get("loyalty")

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

    if rulings:
        text += "\n\n  OFFICIAL RULINGS:"
        for i, ruling in enumerate(rulings, 1):
            text += f"\n  {i}. {ruling}"
    return text


def extract_and_fetch_cards(question: str) -> tuple[str, list[str], list[CardInfo]]:
    matches = CARD_PATTERN.findall(question)
    if not matches:
        return question, [], []

    card_texts = []
    card_infos = []
    for card_name in matches:
        card = fetch_card(card_name.strip())
        if card:
            rulings = []
            rulings_uri = card.get("rulings_uri")
            if rulings_uri:
                rulings = fetch_rulings(rulings_uri)

            card_texts.append(format_card_text(card, rulings))

            oracle = card.get("oracle_text", "")
            if not oracle and "card_faces" in card:
                oracle = "\n---\n".join(f.get("oracle_text", "") for f in card["card_faces"])

            image_url = None
            if "image_uris" in card:
                image_url = card["image_uris"].get("large")
            elif "card_faces" in card and card["card_faces"]:
                image_url = card["card_faces"][0].get("image_uris", {}).get("large")

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


def build_rag_prompt(
    question: str,
    game_id: str | None = None,
    k: int = 8,
    threshold: float = 1.2,
) -> tuple[str, int, int]:
    """
    Reproduit la logique RAG de /ask et retourne (prompt, chunks_used, cards_used).
    """
    clean_question, card_texts, _ = extract_and_fetch_cards(question)

    search_query = clean_question
    if card_texts:
        keywords = []
        mtg_kw = [
            "target", "return", "untap", "sacrifice", "counter", "destroy",
            "exile", "draw", "discard", "damage", "tap", "creature", "spell",
            "stack", "resolve", "copy", "trigger", "cast", "magecraft",
            "attack", "instant", "sorcery", "ability", "permanent",
        ]
        for ct in card_texts:
            for kw in mtg_kw:
                if kw in ct.lower():
                    keywords.append(kw)
        if keywords:
            search_query += " " + " ".join(set(keywords))

    search_kwargs = {"k": k}
    if game_id:
        search_kwargs["filter"] = {"game_id": game_id}

    results = vectorstore.similarity_search_with_score(search_query, **search_kwargs)
    relevant = [(doc, score) for doc, score in results if score < threshold]

    role = GAME_PROMPTS.get(game_id, DEFAULT_PROMPT) if game_id else DEFAULT_PROMPT
    rules_context = "\n\n".join(doc.page_content for doc, _ in relevant)
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
    return prompt, len(relevant), len(card_texts)
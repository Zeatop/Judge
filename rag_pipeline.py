# rag_pipeline.py
"""
Pipeline RAG : recherche dans ChromaDB + génération via Mistral.
Usage :
    python rag_pipeline.py                          → Question par défaut (MTG)
    python rag_pipeline.py "ma question"            → Question custom
    python rag_pipeline.py "ma question" --game mtg → Filtrer par jeu
"""

import argparse
from db import vectorstore
from langchain_ollama import OllamaLLM

# ── Prompts par jeu ─────────────────────────────────────────────────
GAME_PROMPTS = {
    "mtg": "You are a strict Magic: The Gathering judge.",
    "Catan": "You are an expert on Catan board game rules.",
    "Monopoly": "You are an expert on Monopoly board game rules.",
}
DEFAULT_PROMPT = "You are a board game rules expert."


# ── LLM ─────────────────────────────────────────────────────────────
print("🤖 Initialisation de Mistral...")
llm = OllamaLLM(model="mistral:7b", temperature=0.1, num_ctx=4096)
print("✅ Mistral prêt")


# ── Core ────────────────────────────────────────────────────────────
def ask(question: str, game_id: str | None = None, k: int = 16, threshold: float = 0.5) -> str:
    """
    Pose une question au RAG.
    - game_id : filtre les chunks par jeu (None = tous les jeux)
    - k       : nombre de chunks à récupérer
    - threshold : score max de distance (plus bas = plus strict)
    """
    search_kwargs = {"k": k}
    if game_id:
        search_kwargs["filter"] = {"game_id": game_id}

    results = vectorstore.similarity_search_with_score(question, **search_kwargs)
    relevant = [(doc, score) for doc, score in results if score < threshold]

    if not relevant:
        return "Aucune règle pertinente trouvée."

    # Détermine le jeu dominant dans les résultats (pour adapter le prompt)
    if game_id:
        role = GAME_PROMPTS.get(game_id, DEFAULT_PROMPT)
    else:
        # Auto-détection : prend le game_id le plus fréquent dans les résultats
        games_found = [doc.metadata.get("game_id", "") for doc, _ in relevant]
        top_game = max(set(games_found), key=games_found.count)
        role = GAME_PROMPTS.get(top_game, DEFAULT_PROMPT)

    context = "\n\n".join([doc.page_content for doc, _ in relevant])

    prompt = f"""{role}
Answer ONLY using the rules provided below.
Do NOT use any external knowledge.
Do NOT invent or reference rules that are not in the text below.
If the answer is not explicitly in the rules provided, say "I cannot find this in the provided rules."
Cite the exact rule number(s) you used.

Rules:
{context}

Question: {question}
Answer:"""

    return llm.invoke(prompt)


# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG board game rules")
    parser.add_argument("question", nargs="?",
                        default="Someone casts a spell that returns a targeted creature to my hand "
                                "and untaps my opponent's 2 lands. In response I sacrifice the "
                                "targeted creature, what happens?")
    parser.add_argument("--game", type=str, default=None,
                        help="Filtrer par jeu (mtg, Catan, Monopoly)")
    parser.add_argument("-k", type=int, default=8, help="Nombre de chunks à chercher")
    parser.add_argument("--threshold", type=float, default=1.2, help="Score max de distance")
    parser.add_argument("--debug", action="store_true", help="Afficher les chunks retenus")
    args = parser.parse_args()

    print(f"\nQ: {args.question}")
    if args.game:
        print(f"🎮 Filtre jeu : {args.game}")

    if args.debug:
        search_kwargs = {"k": args.k}
        if args.game:
            search_kwargs["filter"] = {"game_id": args.game}
        results = vectorstore.similarity_search_with_score(args.question, **search_kwargs)
        relevant = [(doc, score) for doc, score in results if score < args.threshold]
        print(f"\n🔍 {len(relevant)} chunks retenus :")
        for i, (chunk, score) in enumerate(relevant):
            game = chunk.metadata.get("game_id", "?")
            print(f"  [{i+1}] game={game} | score={score:.3f} | {chunk.page_content[:80]}...")

    response = ask(args.question, game_id=args.game, k=args.k, threshold=args.threshold)
    print(f"\nA: {response}")
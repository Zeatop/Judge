# indexer.py
"""
Indexation des règles de jeux dans ChromaDB.
Usage :
    python indexer.py              → Indexe tous les jeux
    python indexer.py --test       → Indexe + lance un test de recherche
    python indexer.py --reset      → Vide la DB avant de ré-indexer
"""

import argparse
import hashlib
import shutil
import os

from langchain_chroma import Chroma
from pdfProcessor import PDFProcessor
from db import embeddings, CHROMA_DIR

# ── Configuration des jeux ──────────────────────────────────────────
GAMES = [
    {
        "game_id": "mtg",
        "pdf_path": "./rules/Magic the gathering/rulebook.pdf",
    },
    {
        "game_id": "Catan",
        "pdf_path": "./rules/RAG/Catan.pdf",
    },
    {
        "game_id": "Monopoly",
        "pdf_path": "./rules/RAG/Monopoly.pdf",
    },
]


# ── Helpers ─────────────────────────────────────────────────────────
def make_chunk_id(game_id: str, index: int, content: str) -> str:
    """ID déterministe pour éviter les doublons à chaque ré-indexation."""
    digest = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"{game_id}_{index}_{digest}"


def reset_db():
    """Vide le contenu de la base ChromaDB (sans supprimer le dossier monté)."""
    if os.path.exists(CHROMA_DIR):
        print("🗑️  Suppression du contenu de ChromaDB...")
        for entry in os.scandir(CHROMA_DIR):
            if entry.is_dir():
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)


def get_vectorstore():
    return Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)


def index_all():
    """Indexe tous les jeux définis dans GAMES."""
    vs = get_vectorstore()
    for game in GAMES:
        print(f"\n📖 Indexation de {game['game_id']}...")
        processor = PDFProcessor(
            file_path=game["pdf_path"],
            game_id=game["game_id"],
        )
        chunks = processor.process_pdf()

        ids = [
            make_chunk_id(game["game_id"], i, chunk.page_content)
            for i, chunk in enumerate(chunks)
        ]

        vs.add_documents(chunks, ids=ids)
        print(f"✅ {len(chunks)} chunks indexés pour {game['game_id']}")

    print(f"\n🎉 Total dans ChromaDB : {vs._collection.count()} chunks")


def test_search():
    """Recherche de test pour vérifier que l'indexation fonctionne."""
    query = "can I play a sorcery during an opponent's turn?"
    print(f"\n🔍 Test : '{query}'")

    results = get_vectorstore().similarity_search_with_score(query, k=5)
    for i, (doc, score) in enumerate(results):
        game = doc.metadata.get("game_id", "?")
        print(f"  [{i+1}] game={game} | score={score:.3f} | {doc.page_content[:80]}...")


# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Indexation des règles de jeux")
    parser.add_argument("--test", action="store_true", help="Test de recherche après indexation")
    parser.add_argument("--reset", action="store_true", help="Vider la DB avant de ré-indexer")
    args = parser.parse_args()

    if args.reset:
        reset_db()

    index_all()

    if args.test:
        test_search()
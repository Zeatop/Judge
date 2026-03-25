# indexer.py
from pdfProcessor import PDFProcessor
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

GAMES = [
    {
        "game_id": "mtg",
        "pdf_path": "./rules/Magic the gathering/rulebook.pdf",
        "is_mtg_rules": True
    },
    {
        "game_id": "Catan",
        "pdf_path": "./rules/RAG/Catan.pdf",
        "is_mtg_rules": False
    },
    {
        "game_id": "Monopoly",
        "pdf_path": "./rules/RAG/Monopoly.pdf",
        "is_mtg_rules": False
    },
]

embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"}
)

# Charge la DB existante ou en crée une nouvelle
vectorstore = Chroma(
    persist_directory="./chroma_db",
    embedding_function=embeddings
)

for game in GAMES:
    print(f"\n📖 Indexation de {game['game_id']}...")
    processor = PDFProcessor(
        file_path=game["pdf_path"],
        game_id=game["game_id"],
        is_mtg_rules=game["is_mtg_rules"]
    )
    chunks = processor.process_pdf()
    vectorstore.add_documents(chunks)
    print(f"✅ {len(chunks)} chunks indexés pour {game['game_id']}")

print(f"\n🎉 Total dans ChromaDB : {vectorstore._collection.count()} chunks")
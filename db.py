# db.py
"""
Module partagé : embeddings + vectorstore ChromaDB.
Importé par indexer.py et rag_pipeline.py.
"""

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from torch import cuda

device = 'cuda' if cuda.is_available() else 'cpu'
print(f"Using device: {device}")

CHROMA_DIR = "./chroma_db"

print("📦 Chargement des embeddings...")
embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    model_kwargs={'device': device},
    encode_kwargs={'device': device, 'batch_size': 32}
)
print("✅ Embeddings chargés")

print("📂 Connexion à ChromaDB...")
vectorstore = Chroma(
    persist_directory=CHROMA_DIR,
    embedding_function=embeddings,
)
print(f"✅ ChromaDB connecté — {vectorstore._collection.count()} chunks")
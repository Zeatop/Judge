# db.py
"""
Module partagé : embeddings + vectorstore ChromaDB.
Importé par indexer.py et rag_pipeline.py.
"""

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
import torch

EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"

if torch.cuda.is_available():
    device = "cuda"
elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    device = "mps"
else:
    device = "cpu"
print(f"Using device: {device}")

# Note : HuggingFace embeddings ne supportent pas MPS, forcer CPU pour encode
encode_device = "cuda" if device == "cuda" else "cpu"

CHROMA_DIR = "./chroma_db"

print("📦 Chargement des embeddings...")
embeddings = HuggingFaceEmbeddings(
    model_name=EMBEDDING_MODEL,
    model_kwargs={'device': encode_device},
    encode_kwargs={'device': encode_device, 'batch_size': 32}
)
print("✅ Embeddings chargés")

print("📂 Connexion à ChromaDB...")
vectorstore = Chroma(
    persist_directory=CHROMA_DIR,
    embedding_function=embeddings,
)
print(f"✅ ChromaDB connecté — {vectorstore._collection.count()} chunks")
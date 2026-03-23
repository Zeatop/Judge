# vectorstore.py
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from pdfProcessor import PDFProcessor

# 1. Charger et chunker le PDF
processor = PDFProcessor("./rules/Magic the gathering/rulebook.pdf", is_mtg_rules=True)
chunks = processor.process_pdf()

# 2. Initialiser les embeddings
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# 3. Stocker dans ChromaDB
print("Indexation des chunks dans ChromaDB...")
vectorstore = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="./chroma_db"  # sauvegarde sur disque
)

print(f"✅ {vectorstore._collection.count()} chunks indexés")

# 4. Test de recherche réelle
query = "can i play a sorcery during an apponent\'s turn ?"
results = vectorstore.similarity_search(query, k=3)

print(f"\nQuery : '{query}'")
print("\n--- CHUNKS LES PLUS PERTINENTS ---")
for i, doc in enumerate(results):
    print(f"\n[Résultat {i+1}]")
    print(doc.page_content[:300])
    print("-" * 50)
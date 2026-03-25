# rag_pipeline.py
import sys

def log(msg):
    print(msg, flush=True)

log("🚀 Démarrage...")

from langchain_huggingface import HuggingFaceEmbeddings
log("✅ LangChain HuggingFace importé")

from langchain_chroma import Chroma
log("✅ Chroma importé")

from langchain_ollama import OllamaLLM
log("✅ Ollama importé")

log("📦 Chargement des embeddings (peut prendre 30s)...")
embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"}
)
log("✅ Embeddings chargés")

log("📂 Connexion à ChromaDB...")
vectorstore = Chroma(
    persist_directory="./chroma_db",
    embedding_function=embeddings
)
log(f"✅ ChromaDB connecté — {vectorstore._collection.count()} chunks")

log("🤖 Initialisation de Mistral...")
llm = OllamaLLM(model="mistral:7b", temperature=0.0, num_ctx=4096)
log("✅ Mistral prêt")

def ask(question: str) -> str:
    results = vectorstore.similarity_search_with_score(question, k=8)
    relevant = [(doc, score) for doc, score in results if score < 0.8]
    
    if not relevant:
        return "Aucune règle pertinente trouvée."
    
    context = "\n\n".join([doc.page_content for doc, _ in relevant])
    
    prompt = f"""You are a strict Magic: The Gathering judge.
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

if __name__ == "__main__":
    question = "someone casts a spell that return targeted creature in my hand and untaps my opponent 2 lands. In response I sacrifice the targeted creature, what happens ?"
    
    log(f"\nQ: {question}")
    log("\n🔍 Recherche des chunks pertinents...")
    
    results = vectorstore.similarity_search_with_score(question, k=500)
    relevant = [(doc, score) for doc, score in results if score < 1.35]
    
    log(f"✅ {len(relevant)} chunks retenus")
    for i, (chunk, score) in enumerate(relevant):
        log(f"  [Chunk {i+1}] score={score:.3f} | {chunk.page_content[:80]}...")
    
    context = "\n\n".join([doc.page_content for doc, _ in relevant])
    
    prompt = f"""You are a strict Magic: The Gathering judge.
Answer ONLY using the rules provided below.
Do NOT use any external knowledge.
Do NOT invent or reference rules that are not in the text below.
If the answer is not explicitly in the rules provided, say "I cannot find this in the provided rules."
Cite the exact rule number(s) you used.

Rules:
{context}

Question: {question}
Answer:"""

    log("\n🤖 Envoi à Mistral...")
    response = llm.invoke(prompt)
    log("\n✅ Réponse reçue !")
    log(f"\nA: {response}")
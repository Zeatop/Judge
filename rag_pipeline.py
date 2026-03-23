# rag_pipeline.py
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_ollama import OllamaLLM

embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"}  # ← libère la VRAM pour Ollama
)
vectorstore = Chroma(
    persist_directory="./chroma_db",
    embedding_function=embeddings
)
llm = OllamaLLM(model="mistral:7b", num_gpu=20, temperature=0.0, num_ctx=4096)

def ask(question: str) -> str:
    # 1. Récupère les chunks pertinents
    chunks = vectorstore.similarity_search(question, k=50)
    context = "\n\n".join([c.page_content for c in chunks])
    
    # 2. Construit le prompt
    prompt = f"""You are a Magic: The Gathering judge. Answer based only on the rules provided.
If the answer isn't in the rules, say so.

Rules:
{context}

Question: {question}
Answer:"""
    
    # 3. Appelle Ollama
    return llm.invoke(prompt)

if __name__ == "__main__":
    question = "Can I cast sorceries during combat phase ?"
    print(f"Q: {question}")
    
    print("🔍 Recherche des chunks pertinents...")
    chunks = vectorstore.similarity_search(question, k=30)
    print(f"✅ {len(chunks)} chunks trouvés")
    
    for i, chunk in enumerate(chunks):
        print(f"  [Chunk {i+1}] {chunk.page_content[:80]}...")
    
    context = "\n\n".join([c.page_content for c in chunks])
    
    print("\n🤖 Envoi à Mistral...")
    prompt = f"""You are a Magic: The Gathering judge. Answer based only on the rules provided.
                If the answer isn't in the rules, say so.
                Rules:
                {context}
                Question: {question}
                Answer:"""
                    
    response = llm.invoke(prompt)
    print(f"\n✅ Réponse reçue !")
    print(f"\nA: {response}")

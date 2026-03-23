import re
from langchain_text_splitters import RecursiveCharacterTextSplitter as rs
from langchain_community.document_loaders import PyPDFLoader

class PDFProcessor:

    def __init__(self, file_path, is_mtg_rules=False):
        self.file_path = file_path
        self.is_mtg_rules = is_mtg_rules

    def extract_text(self):
        loader = PyPDFLoader(self.file_path)
        documents = loader.load()
        print(f"Extracted {len(documents)} documents from the PDF.")
        return documents

    def split_text(self, documents):
        if self.is_mtg_rules:
            return self._split_mtg(documents)
        
        splitter = rs(
            chunk_size=800,    # un peu plus grand pour garder les règles entières
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " "]
        )
        return splitter.split_documents(documents)

    def _split_mtg(self, documents):
        filtered = [doc for doc in documents if doc.metadata.get("page", 0) >= 4]
        
        # Reconstitue le texte complet
        full_text = "\n".join([doc.page_content for doc in filtered])
        
        # Découpe à chaque début de règle numérotée (ex: "100.1", "702.15a")
        rule_pattern = r'(?=\n\d{3}\.\d+[a-z]?\.\s)'
        chunks = re.split(rule_pattern, full_text)
        
        # Regroupe par paquets de 3 règles pour avoir des chunks assez denses
        grouped = []
        for i in range(0, len(chunks), 3):
            group = " ".join(chunks[i:i+3]).strip()
            if len(group) > 50:
                grouped.append(group)
        
        # Recrée des Documents LangChain
        from langchain_core.documents import Document
        return [Document(page_content=chunk, metadata={"game_id": "mtg"}) for chunk in grouped]

    def process_pdf(self):
        documents = self.extract_text()
        split_documents = self.split_text(documents)
        return split_documents
    
PDF_processor = PDFProcessor("./rules/Magic the gathering/rulebook.pdf", is_mtg_rules=True)
processed_docs = PDF_processor.process_pdf()
print(f"Processed {len(processed_docs)} documents.")
print("\n--- APERÇU DES CHUNKS ---")
for i, doc in enumerate(processed_docs[:20]):
    print(f"\n[Chunk {i+1}] ({len(doc.page_content)} chars) - page {doc.metadata.get('page', '?')}")
    print(doc.page_content)
    print("-" * 50)
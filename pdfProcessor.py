import re
from langchain_text_splitters import RecursiveCharacterTextSplitter as rs
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document


class PDFProcessor:

    def __init__(self, file_path, game_id):
        self.file_path = file_path
        self.game_id = game_id

    def extract_text(self):
        loader = PyPDFLoader(self.file_path)
        documents = loader.load()
        print(f"Extracted {len(documents)} documents from the PDF.")
        return documents

    def split_text(self, documents):
        if self.game_id == "mtg":
            return self._split_mtg(documents)
        
        splitter = rs(
            chunk_size=800,    # un peu plus grand pour garder les règles entières
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " "]
        )
        chunks = splitter.split_documents(documents)
        # Tag chaque chunk avec le game_id
        for chunk in chunks:
            chunk.metadata["game_id"] = self.game_id
        return chunks

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
        return [Document(page_content=chunk, metadata={"game_id": self.game_id}) for chunk in grouped]

    def process_pdf(self):
        documents = self.extract_text()
        split_documents = self.split_text(documents)
        return split_documents

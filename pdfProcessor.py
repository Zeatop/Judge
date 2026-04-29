import re
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document


class PDFProcessor:

    def __init__(self, file_path, game_id, lang="fr"):
        self.file_path = file_path
        self.game_id = game_id
        self.lang = lang

    def extract_text(self):
        loader = PyPDFLoader(self.file_path)
        documents = loader.load()
        print(f"Extracted {len(documents)} pages from the PDF.")
        return documents

    def process_pdf(self):
        """Pipeline principal : extraction → formatage → chunking."""
        documents = self.extract_text()

        if self.game_id == "mtg":
            return self._split_mtg(documents)

        # ── Flow Claude pour les jeux non-MTG ───────────────────────
        full_text = "\n".join([doc.page_content for doc in documents])
        formatted_text = self._format_with_claude(full_text)
        chunks = self._split_formatted(formatted_text)
        return chunks

    # ── Formatage via Claude ────────────────────────────────────────

    def _format_with_claude(self, raw_text: str) -> str:
        """
        Envoie le texte brut à Claude pour le reformater en VERSION RAG.
        Gère les gros documents en les découpant par batches de ~15 pages.
        """
        from llm_provider import ClaudeProvider
        from var import ANTHROPIC_API_KEY

        formatter = ClaudeProvider(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            temperature=0.0,
            timeout=120.0,
            api_key=ANTHROPIC_API_KEY,
        )

        # Découper en batches si le texte est trop long (~3000 chars/page)
        max_chars_per_batch = 30_000  # ~8-10 pages pour rester dans le timeout
        if len(raw_text) <= max_chars_per_batch:
            batches = [raw_text]
        else:
            batches = self._split_into_batches(raw_text, max_chars_per_batch)

        formatted_parts = []
        for i, batch in enumerate(batches):
            print(f"  📝 Formatage Claude batch {i + 1}/{len(batches)}...")
            prompt = self._build_format_prompt(batch, i, len(batches))
            result = formatter.invoke(prompt)
            formatted_parts.append(result.strip())

        return "\n\n".join(formatted_parts)

    def _split_into_batches(self, text: str, max_chars: int) -> list[str]:
        """Découpe le texte en batches en coupant sur les sauts de ligne."""
        batches = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > max_chars and current:
                batches.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            batches.append(current)
        return batches

    def _build_format_prompt(self, text_batch: str, batch_index: int, total_batches: int) -> str:
        """Construit le prompt de formatage VERSION RAG pour Claude."""
        lang_instruction = "Travaille en français." if self.lang == "fr" else "Work in English."
        batch_context = ""
        if total_batches > 1:
            batch_context = (
                f"\nCeci est le batch {batch_index + 1}/{total_batches} du document. "
                f"Formate uniquement ce passage, mais garde la cohérence globale."
            )

        return f"""Tu es un assistant spécialisé dans le reformatage de règles de jeux de société pour un système RAG (Retrieval-Augmented Generation).

Reformate le texte de règles ci-dessous en VERSION RAG uniquement.

Règles de formatage VERSION RAG :
- Texte brut pur, AUCUN markdown (pas de #, **, -, ```, etc.)
- AUCUN tableau, AUCUNE liste à puces, AUCUNE numérotation de pages
- Organisé en paragraphes autonomes de 3 à 6 phrases, séparés par des lignes vides
- Chaque paragraphe doit être auto-suffisant et compréhensible isolément (rappeler le contexte)
- Le nom du jeu "{self.game_id}" doit apparaître dans le premier paragraphe et tous les 4-5 paragraphes
- Termes spécifiques cohérents et identiques partout
- Tableaux convertis en phrases déclaratives
- Cas particuliers en paragraphes séparés
- Reformule les passages confus sans changer le sens
- Conserve tous les exemples et ajoutes-en si nécessaire
- Ne supprime aucune règle même mineure
- Signale les ambiguïtés entre crochets
- N'invente jamais de règle
{batch_context}
{lang_instruction}

Retourne UNIQUEMENT le texte reformaté, sans introduction ni commentaire.

=== TEXTE À REFORMATER ===
{text_batch}"""

    # ── Chunking post-formatage ─────────────────────────────────────

    def _split_formatted(self, formatted_text: str) -> list[Document]:
        """
        Split le texte formatté par Claude sur les doubles sauts de ligne.
        Chaque paragraphe autonome = 1 chunk.
        """
        paragraphs = [p.strip() for p in formatted_text.split("\n\n") if p.strip()]

        # Fusionner les paragraphes trop courts (< 100 chars) avec le suivant
        chunks = []
        buffer = ""
        for para in paragraphs:
            if buffer:
                buffer = buffer + "\n\n" + para
                if len(buffer) >= 200:
                    chunks.append(buffer)
                    buffer = ""
            elif len(para) < 100 and para:
                buffer = para
            else:
                chunks.append(para)
        if buffer:
            chunks.append(buffer)

        print(f"  ✅ {len(chunks)} chunks créés après formatage Claude")
        return [
            Document(page_content=chunk, metadata={"game_id": self.game_id, "lang": self.lang})
            for chunk in chunks
        ]

    # ── Path MTG (inchangé) ─────────────────────────────────────────

    def _split_mtg(self, documents):
        skipped_pages = int(os.getenv("SKIPPED_MTG_PAGES", 0))
        filtered = [doc for doc in documents if doc.metadata.get("page", 0) >= skipped_pages]

        full_text = "\n".join([doc.page_content for doc in filtered])

        # Découpe à chaque début de règle numérotée (ex: "100.1", "702.15a")
        rule_pattern = r'(?=\n\d{3}\.\d+[a-z]?\.\s)'
        chunks = re.split(rule_pattern, full_text)

        # Regroupe par paquets de 3 règles pour avoir des chunks assez denses
        grouped = []
        for i in range(0, len(chunks), 3):
            group = " ".join(chunks[i:i + 3]).strip()
            if len(group) > 50:
                grouped.append(group)

        return [Document(page_content=chunk, metadata={"game_id": self.game_id}) for chunk in grouped]
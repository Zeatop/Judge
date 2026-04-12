# var.py
"""
Variables de configuration centralisées.
Modifie ce fichier pour changer de provider ou de modèle.
"""

# "ollama" = local via Ollama | "claude" = API Anthropic
import os


LLM_PROVIDER = "claude"

# Modèle à utiliser
# Ollama  : "mistral:7b", "qwen2.5:32b", "mixtral:8x22b", ...
# Claude  : "claude-sonnet-4-20250514", "claude-opus-4-20250514", ...
LLM_MODEL = "claude-opus-4-6"

# Clé API Anthropic (requis uniquement si LLM_PROVIDER = "claude")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your-anthropic-api-key")
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY", "your-chroma-api-key")

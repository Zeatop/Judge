# var.py
"""
Variables de configuration centralisées.
Tout est lu depuis des variables d'environnement pour la production.
"""

import os

# "ollama" = local via Ollama | "claude" = API Anthropic
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "claude")

# Modèle à utiliser
LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-4-6")

# Clé API Anthropic (requis uniquement si LLM_PROVIDER = "claude")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
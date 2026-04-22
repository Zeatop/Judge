# available_models.py
"""
Catalogue des modèles LLM exposés à l'utilisateur via l'UI.
Ajoute/retire des entrées ici pour contrôler ce qui est sélectionnable.
"""

AVAILABLE_MODELS = [
    {
        "id": "claude-opus-4-6",
        "provider": "claude",
        "model": "claude-opus-4-6",
        "label": "Claude Opus 4.6",
        "description": "Le plus puissant, idéal pour MTG complexe",
        "speed": "medium",
        "cost_tier": "high",
    },
    {
        "id": "claude-sonnet-4",
        "provider": "claude",
        "model": "claude-sonnet-4-20250514",
        "label": "Claude Sonnet 4",
        "description": "Bon compromis qualité/prix",
        "speed": "fast",
        "cost_tier": "medium",
    },
    {
        "id": "deepseek-reasoner",
        "provider": "deepseek",
        "model": "deepseek-reasoner",
        "label": "DeepSeek Reasoner",
        "description": "Raisonnement approfondi, lent mais bon marché",
        "speed": "slow",
        "cost_tier": "low",
    },
    {
        "id": "deepseek-chat",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "label": "DeepSeek Chat",
        "description": "Rapide et très bon marché",
        "speed": "fast",
        "cost_tier": "low",
    },
]

MODELS_BY_ID = {m["id"]: m for m in AVAILABLE_MODELS}
DEFAULT_MODEL_ID = "claude-opus-4-6"
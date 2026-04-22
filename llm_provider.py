# llm_provider.py
"""
Abstraction LLM : permet de switcher entre Ollama (local) et Claude (API Anthropic).
Usage :
    from llm_provider import get_provider

    llm = get_provider()          # Lit LLM_PROVIDER depuis .env ou env vars
    answer = llm.invoke(prompt)
"""

import os
import httpx
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Interface commune pour tous les providers LLM."""

    @abstractmethod
    def invoke(self, prompt: str) -> str:
        """Envoie un prompt et retourne la réponse texte."""
        ...


class OllamaProvider(LLMProvider):
    """Provider local via Ollama."""

    def __init__(self, model: str = "mistral:7b", temperature: float = 0.0, num_ctx: int = 4096):
        from langchain_ollama import OllamaLLM
        self.llm = OllamaLLM(model=model, temperature=temperature, num_ctx=num_ctx)
        self.model = model

    def invoke(self, prompt: str) -> str:
        return self.llm.invoke(prompt)

    def __repr__(self):
        return f"OllamaProvider(model={self.model})"


class ClaudeProvider(LLMProvider):
    """Provider via l'API Anthropic (Claude)."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 120.0,
        api_key: str | None = None,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        from var import ANTHROPIC_API_KEY
        self.api_key = api_key or ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY manquant. "
                "Définis-le dans ton .env ou en variable d'environnement."
            )

    def invoke(self, prompt: str, max_retries: int = 3) -> str:
        """
        Sépare le prompt en system + user message.
        Convention : tout avant 'Question:' = system, le reste = user.
        Retry automatique sur erreurs 5xx et 429 (rate limit).
        """
        import time as _time

        # Sépare system prompt et question
        if "Question:" in prompt:
            parts = prompt.split("Question:", 1)
            system_text = parts[0].strip()
            user_text = "Question:" + parts[1].strip()
        else:
            system_text = ""
            user_text = prompt

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": user_text}],
        }
        if system_text:
            payload["system"] = system_text

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(max_retries):
            resp = httpx.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                return "".join(
                    block["text"]
                    for block in data.get("content", [])
                    if block.get("type") == "text"
                )

            # Retry sur erreurs serveur (5xx) et rate limit (429)
            if resp.status_code in (429, 500, 502, 503, 529):
                wait = 2 ** attempt  # 1s, 2s, 4s
                print(f"⚠️  Claude API {resp.status_code}, retry {attempt + 1}/{max_retries} dans {wait}s...")
                last_error = f"Claude API error {resp.status_code}: {resp.text}"
                _time.sleep(wait)
                continue

            # Erreur non-retriable (400, 401, 403...) → crash immédiat
            raise RuntimeError(f"Claude API error {resp.status_code}: {resp.text}")

        raise RuntimeError(f"Claude API : échec après {max_retries} tentatives. Dernière erreur : {last_error}")

    def __repr__(self):
        return f"ClaudeProvider(model={self.model})"

class DeepSeekProvider(LLMProvider):
    """Provider via l'API DeepSeek (format compatible OpenAI)."""

    API_URL = "https://api.deepseek.com/chat/completions"

    # Modèles qui ignorent temperature/top_p/penalties (mode thinking)
    REASONING_MODELS = {"deepseek-reasoner"}

    def __init__(
        self,
        model: str = "deepseek-reasoner",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: float = 180.0,       # reasoner peut mettre 30-60s
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        from var import DEEPSEEK_API_KEY
        self.api_key = api_key or DEEPSEEK_API_KEY
        if not self.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY manquant. "
                "Définis-le dans ton .env ou en variable d'environnement."
            )
        self.api_url = base_url or self.API_URL

    def invoke(self, prompt: str, max_retries: int = 3) -> str:
        import time as _time

        # Même convention que Claude : split sur 'Question:'
        if "Question:" in prompt:
            parts = prompt.split("Question:", 1)
            system_text = parts[0].strip()
            user_text = "Question:" + parts[1].strip()
        else:
            system_text = ""
            user_text = prompt

        messages = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": user_text})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
        # deepseek-reasoner ignore / refuse temperature
        if self.model not in self.REASONING_MODELS:
            payload["temperature"] = self.temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(max_retries):
            resp = httpx.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    raise RuntimeError(f"DeepSeek API: réponse sans choices : {data}")
                # On ne garde que content, pas reasoning_content (CoT interne)
                return choices[0]["message"].get("content", "") or ""

            if resp.status_code in (429, 500, 502, 503, 529):
                wait = 2 ** attempt
                print(f"⚠️  DeepSeek API {resp.status_code}, retry {attempt + 1}/{max_retries} dans {wait}s...")
                last_error = f"DeepSeek API error {resp.status_code}: {resp.text}"
                _time.sleep(wait)
                continue

            raise RuntimeError(f"DeepSeek API error {resp.status_code}: {resp.text}")

        raise RuntimeError(f"DeepSeek API : échec après {max_retries} tentatives. Dernière erreur : {last_error}")

    def __repr__(self):
        return f"DeepSeekProvider(model={self.model})"
# ── Factory ─────────────────────────────────────────────────────────

PROVIDERS = {
    "ollama": OllamaProvider,
    "claude": ClaudeProvider,
    "deepseek": DeepSeekProvider,
}


def get_provider(provider_name: str | None = None, **kwargs) -> LLMProvider:
    """
    Crée le provider LLM selon la config.

    Priorité :
      1. Argument provider_name
      2. Variable d'env LLM_PROVIDER
      3. Défaut : "ollama"

    kwargs sont passés au constructeur du provider.
    Exemples :
        get_provider("claude", model="claude-sonnet-4-20250514")
        get_provider("ollama", model="qwen2.5:32b", num_ctx=8192)
    """
    from var import LLM_PROVIDER as default_provider
    name = (provider_name or default_provider).lower()

    if name not in PROVIDERS:
        raise ValueError(f"Provider inconnu : '{name}'. Choix : {list(PROVIDERS.keys())}")

    provider = PROVIDERS[name](**kwargs)
    print(f"🤖 LLM provider : {provider}")
    return provider

# ── Cache d'instances ──────────────────────────────────────────────

_PROVIDER_CACHE: dict[tuple[str, str], LLMProvider] = {}


def get_cached_provider(provider_name: str, model: str) -> LLMProvider:
    """
    Retourne une instance LLMProvider, mise en cache par (provider, model).
    Évite de recréer un client HTTP à chaque requête.
    """
    key = (provider_name.lower(), model)
    if key not in _PROVIDER_CACHE:
        _PROVIDER_CACHE[key] = get_provider(provider_name, model=model)
    return _PROVIDER_CACHE[key]
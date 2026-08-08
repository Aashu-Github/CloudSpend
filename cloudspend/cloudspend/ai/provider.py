from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import requests

from cloudspend.config import Settings


class AIProviderError(RuntimeError):
    pass


class AIProvider(ABC):
    name: str

    @abstractmethod
    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raise NotImplementedError


class NoneProvider(AIProvider):
    name = "none"

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raise AIProviderError("AI_PROVIDER=none. Enable an Ollama-compatible provider to use this feature.")


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        if not model:
            raise AIProviderError("OLLAMA_MODEL must be configured when AI_PROVIDER=ollama.")
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        prompt = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}\n"
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=90,
            )
            response.raise_for_status()
            body = response.json()
            raw = body.get("response", body)
            if isinstance(raw, str):
                return json.loads(raw)
            if isinstance(raw, dict):
                return raw
            raise AIProviderError("AI provider returned an unexpected payload.")
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise AIProviderError(f"AI provider request failed: {type(exc).__name__}") from exc


def get_ai_provider(settings: Settings | None = None) -> AIProvider:
    settings = settings or Settings.from_env()
    if settings.ai_provider == "none":
        return NoneProvider()
    if settings.ai_provider == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model)
    raise AIProviderError(f"Unsupported AI provider: {settings.ai_provider}")

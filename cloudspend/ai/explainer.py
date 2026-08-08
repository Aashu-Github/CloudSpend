from __future__ import annotations

import json

from cloudspend.ai.provider import AIProvider
from cloudspend.models.recommendations import Recommendation

SYSTEM_PROMPT = """Rewrite the supplied deterministic CloudSpend recommendation in plain language. Do not change numbers, rule ID, action, confidence, evidence, or savings. Return JSON with only an 'explanation' string. Do not introduce claims that are absent from the payload."""


def explain(provider: AIProvider, recommendation: Recommendation) -> str:
    payload = recommendation.model_dump(mode="json")
    output = provider.generate_json(SYSTEM_PROMPT, json.dumps(payload))
    text = output.get("explanation")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("AI explanation did not return a valid explanation string.")
    return text.strip()

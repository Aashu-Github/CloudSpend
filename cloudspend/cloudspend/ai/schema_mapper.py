from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from cloudspend.ai.prompts import SCHEMA_MAPPING_SYSTEM_PROMPT
from cloudspend.ai.provider import AIProvider
from cloudspend.models.canonical import CloudResource


class FieldMapping(BaseModel):
    source_field: str
    target_field: str | None = None
    transform: str | None = None
    confidence: float = Field(ge=0, le=1)
    rationale: str


class MappingProposal(BaseModel):
    mapping: list[FieldMapping] = Field(default_factory=list)
    unmapped_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0, le=1)


def propose_mapping(provider: AIProvider, columns: list[str], inferred_types: dict[str, str], samples: list[dict[str, Any]]) -> MappingProposal:
    redacted_samples = []
    for sample in samples[:10]:
        redacted = {}
        for key, value in sample.items():
            text = str(value)
            if any(token in key.lower() for token in ("secret", "token", "password", "access_key")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = text[:120]
        redacted_samples.append(redacted)
    target_schema = CloudResource.model_json_schema()
    user = json.dumps({"columns": columns, "inferred_types": inferred_types, "samples": redacted_samples, "target_schema": target_schema}, default=str)
    output = provider.generate_json(SCHEMA_MAPPING_SYSTEM_PROMPT, user)
    return MappingProposal.model_validate(output)

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


Category = Literal["idle", "rightsize", "schedule", "orphan_storage", "anomaly"]
Confidence = Literal["high", "medium", "low"]
SavingsBasis = Literal["actual", "allocated", "estimated", "unavailable"]


class Evidence(BaseModel):
    key: str
    value: Any
    threshold: Any | None = None
    detail: str | None = None


class Recommendation(BaseModel):
    recommendation_id: UUID = Field(default_factory=uuid4)
    rule_id: str
    rule_version: str
    category: Category
    resource_id: str
    title: str
    suggested_action: str
    confidence: Confidence
    evidence: list[Evidence] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    current_monthly_cost: Decimal | None = None
    estimated_monthly_savings: Decimal | None = None
    savings_basis: SavingsBasis = "unavailable"
    safety_note: str = "Human review required before any infrastructure change."
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("estimated_monthly_savings")
    @classmethod
    def positive_savings(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            return Decimal("0")
        return value

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from cloudspend.models.canonical import CloudResource, MetricSummary


def metric(resource: CloudResource, name: str) -> MetricSummary | None:
    return resource.metrics.get(name)


def observation_days(resource: CloudResource) -> float | None:
    timestamps = [ts for m in resource.metrics.values() for ts in m.timestamps]
    if not timestamps:
        return None
    return max(0.0, (max(timestamps) - min(timestamps)).total_seconds() / 86400.0)


def age_days(created: datetime | None, now: datetime | None = None) -> float | None:
    if created is None:
        return None
    now = now or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created.astimezone(timezone.utc)).total_seconds() / 86400.0)


def lower_confidence(confidence: str, steps: int = 1) -> str:
    levels = ["low", "medium", "high"]
    idx = levels.index(confidence)
    return levels[max(0, idx - steps)]


def money(value: Decimal | None) -> Decimal | None:
    return value.quantize(Decimal("0.01")) if value is not None else None

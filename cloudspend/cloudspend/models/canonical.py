from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


Confidence = Literal["high", "medium", "low"]
ResourceType = Literal["ec2_instance", "ebs_volume"]


class SourceLineage(BaseModel):
    provider_mode: Literal["demo", "file", "live", "canonical", "cur"]
    source_name: str
    source_family: str | None = None
    imported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MetricSummary(BaseModel):
    namespace: str = "AWS/EC2"
    metric_name: str
    unit: str | None = None
    avg: float | None = None
    p95: float | None = None
    max: float | None = None
    min: float | None = None
    samples: int = 0
    missing_ratio: float = 0.0
    burst_score: float | None = None
    timestamps: list[datetime] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)

    @field_validator("missing_ratio")
    @classmethod
    def valid_missing_ratio(cls, value: float) -> float:
        return min(1.0, max(0.0, value))

    @model_validator(mode="after")
    def coherent_series(self) -> "MetricSummary":
        if self.timestamps and len(self.timestamps) != len(self.values):
            raise ValueError("metric timestamps and values must have equal length")
        return self


class CostSummary(BaseModel):
    actual_resource_cost: Decimal | None = None
    allocated_cost: Decimal | None = None
    estimated_resource_cost: Decimal | None = None
    currency: Literal["USD"] = "USD"
    period_start: date | None = None
    period_end: date | None = None
    source: str = "unavailable"
    confidence: Confidence = "low"
    daily_costs: dict[date, Decimal] = Field(default_factory=dict)

    @field_validator("actual_resource_cost", "allocated_cost", "estimated_resource_cost")
    @classmethod
    def nonnegative_cost(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("cost cannot be negative")
        return value

    def best_monthly_cost(self) -> tuple[Decimal | None, str]:
        if self.actual_resource_cost is not None:
            return self.actual_resource_cost, "actual"
        if self.allocated_cost is not None:
            return self.allocated_cost, "allocated"
        if self.estimated_resource_cost is not None:
            return self.estimated_resource_cost, "estimated"
        return None, "unavailable"


class EC2Details(BaseModel):
    instance_type: str
    launch_time: datetime | None = None
    availability_zone: str | None = None
    platform: str | None = None
    architecture: str | None = None
    vpc_id: str | None = None
    private_ip: str | None = None
    schedule_eligible: bool = False


class EBSDetails(BaseModel):
    size_gib: int
    volume_type: str = "gp3"
    encrypted: bool | None = None
    create_time: datetime | None = None
    attachments: list[str] = Field(default_factory=list)
    iops: int | None = None
    throughput: int | None = None


class CloudResource(BaseModel):
    provider: Literal["aws"] = "aws"
    account_id: str | None = None
    region: str = "unknown"
    resource_type: ResourceType
    resource_id: str
    name: str | None = None
    state: str = "unknown"
    tags: dict[str, str] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_lineage: SourceLineage
    ec2: EC2Details | None = None
    ebs: EBSDetails | None = None
    metrics: dict[str, MetricSummary] = Field(default_factory=dict)
    costs: CostSummary = Field(default_factory=CostSummary)
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def matching_details(self) -> "CloudResource":
        if self.resource_type == "ec2_instance" and self.ec2 is None:
            raise ValueError("ec2_instance requires ec2 details")
        if self.resource_type == "ebs_volume" and self.ebs is None:
            raise ValueError("ebs_volume requires ebs details")
        return self

    @property
    def environment(self) -> str:
        for key in ("Environment", "environment", "Env", "env"):
            if key in self.tags:
                return self.tags[key].strip().lower()
        return "unknown"

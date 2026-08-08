from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cloudspend.config import Settings
from cloudspend.models.canonical import CloudResource
from cloudspend.models.recommendations import Recommendation
from cloudspend.optimizer import cost_anomaly, idle_ec2, orphan_ebs, rightsize_ec2, schedule_candidates
from cloudspend.optimizer.pricing import ensure_estimated_cost, monthly_equivalent


@dataclass(slots=True)
class OptimizationResult:
    resources: list[CloudResource]
    recommendations: list[Recommendation]

    @property
    def observed_spend(self) -> Decimal:
        total = Decimal("0")
        for resource in self.resources:
            cost, _ = monthly_equivalent(resource.costs)
            if cost is not None:
                total += cost
        return total.quantize(Decimal("0.01"))

    @property
    def potential_savings(self) -> Decimal:
        # Avoid double-counting multiple EC2 recommendations. Use the largest modeled opportunity per resource.
        by_resource: dict[str, Decimal] = {}
        for rec in self.recommendations:
            if rec.estimated_monthly_savings is None:
                continue
            current = by_resource.get(rec.resource_id, Decimal("0"))
            by_resource[rec.resource_id] = max(current, rec.estimated_monthly_savings)
        return sum(by_resource.values(), Decimal("0")).quantize(Decimal("0.01"))


def optimize(resources: list[CloudResource], settings: Settings | None = None) -> OptimizationResult:
    settings = settings or Settings.from_env()
    recs: list[Recommendation] = []
    for resource in resources:
        ensure_estimated_cost(resource)
        for evaluator in (
            idle_ec2.evaluate,
            rightsize_ec2.evaluate,
            schedule_candidates.evaluate,
            orphan_ebs.evaluate,
            cost_anomaly.evaluate,
        ):
            rec = evaluator(resource, settings)
            if rec is not None:
                recs.append(rec)
    recs.sort(key=lambda r: (r.resource_id, r.category, r.rule_id))
    return OptimizationResult(resources=resources, recommendations=recs)

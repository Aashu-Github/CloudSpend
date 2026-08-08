from __future__ import annotations

from decimal import Decimal

from cloudspend.config import Settings
from cloudspend.models.canonical import CloudResource
from cloudspend.models.recommendations import Evidence, Recommendation
from cloudspend.optimizer.common import metric
from cloudspend.optimizer.pricing import monthly_equivalent

RULE_ID = "EC2-SCHEDULE-001"
RULE_VERSION = "1.0"
ELIGIBLE_ENVS = {"dev", "development", "test", "testing", "stage", "staging", "qa", "sandbox"}


def _business_hour_share(resource: CloudResource) -> float | None:
    cpu = metric(resource, "CPUUtilization")
    if not cpu or not cpu.timestamps or not cpu.values:
        return None
    inside = 0.0
    total = 0.0
    for ts, value in zip(cpu.timestamps, cpu.values, strict=False):
        val = max(0.0, float(value))
        total += val
        if ts.weekday() < 5 and 8 <= ts.hour < 18:
            inside += val
    return inside / total if total > 0 else None


def evaluate(resource: CloudResource, settings: Settings) -> Recommendation | None:
    if resource.resource_type != "ec2_instance" or resource.state.lower() != "running" or not resource.ec2:
        return None
    env = resource.environment
    explicit = resource.ec2.schedule_eligible
    if env in {"prod", "production"} and not explicit:
        return None
    if env not in ELIGIBLE_ENVS and not explicit:
        return None
    share = _business_hour_share(resource)
    if share is None or share < 0.70:
        return None
    current_cost, basis = monthly_equivalent(resource.costs)
    # 10 business hours/day x 5 days = 50 active hours of 168; 70.24% potentially stopped.
    stoppable_fraction = Decimal("0.7024")
    savings = (current_cost * stoppable_fraction).quantize(Decimal("0.01")) if current_cost is not None else None
    return Recommendation(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        category="schedule",
        resource_id=resource.resource_id,
        title="Development/test scheduling candidate",
        suggested_action="Review an off-hours stop/start schedule with the workload owner; validate timezone and on-call needs first.",
        confidence="high" if explicit else "medium",
        evidence=[
            Evidence(key="environment", value=env, threshold="dev/test/staging or explicit eligibility"),
            Evidence(key="explicit_schedule_eligible", value=explicit),
            Evidence(key="business_hour_utilization_share", value=round(share, 3), threshold=">= 0.70", detail="Calculated from CPU samples using 08:00–18:00 UTC weekdays in MVP."),
            Evidence(key="modeled_stoppable_fraction", value=float(stoppable_fraction), detail="10 active business hours/day, weekdays only; storage/network costs are not assumed to disappear."),
        ],
        current_monthly_cost=current_cost,
        estimated_monthly_savings=savings,
        savings_basis=basis,
        safety_note="Scheduling is advisory. Confirm workload timezone, SLAs, batch windows, and owner approval before automation.",
    )

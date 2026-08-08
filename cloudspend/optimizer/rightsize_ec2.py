from __future__ import annotations

from cloudspend.config import Settings
from cloudspend.models.canonical import CloudResource
from cloudspend.models.recommendations import Evidence, Recommendation
from cloudspend.optimizer.common import metric
from cloudspend.optimizer.pricing import downsize_savings, monthly_equivalent

RULE_ID = "EC2-RIGHTSIZE-001"
RULE_VERSION = "1.0"


def evaluate(resource: CloudResource, settings: Settings) -> Recommendation | None:
    if resource.resource_type != "ec2_instance" or resource.state.lower() != "running" or not resource.ec2:
        return None
    cpu = metric(resource, "CPUUtilization")
    if not cpu or cpu.avg is None or cpu.p95 is None:
        return None
    if cpu.avg >= settings.rightsize_cpu_avg_threshold or cpu.p95 >= settings.rightsize_cpu_p95_threshold:
        return None
    if cpu.max is not None and cpu.max >= 80:
        return None
    if cpu.burst_score is not None and cpu.burst_score >= 5 and (cpu.max or 0) >= 60:
        return None
    memory = metric(resource, "mem_used_percent") or metric(resource, "MemoryUtilization")
    if memory and memory.p95 is not None and memory.p95 >= 40:
        return None

    target, savings = downsize_savings(resource)
    if target is None:
        return None
    current_cost, basis = monthly_equivalent(resource.costs)
    missing: list[str] = []
    confidence = "high"
    if memory is None or memory.p95 is None:
        missing.append("memory utilization")
        confidence = "medium"
    if savings is None:
        missing.append("pricing snapshot for one-size-down target")
        confidence = "low"
    return Recommendation(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        category="rightsize",
        resource_id=resource.resource_id,
        title=f"Rightsizing candidate: {resource.ec2.instance_type} → {target}",
        suggested_action=f"Review workload requirements and benchmark a move from {resource.ec2.instance_type} to {target} before resizing.",
        confidence=confidence,
        evidence=[
            Evidence(key="cpu_avg_percent", value=cpu.avg, threshold=f"< {settings.rightsize_cpu_avg_threshold}"),
            Evidence(key="cpu_p95_percent", value=cpu.p95, threshold=f"< {settings.rightsize_cpu_p95_threshold}"),
            Evidence(key="cpu_max_percent", value=cpu.max, threshold="no high burst/spike"),
            Evidence(key="memory_p95_percent", value=memory.p95 if memory else "unknown", threshold="< 40% strengthens confidence"),
            Evidence(key="candidate_instance_type", value=target),
        ],
        missing_signals=missing,
        current_monthly_cost=current_cost,
        estimated_monthly_savings=savings,
        savings_basis="estimated" if savings is not None else basis,
    )

from __future__ import annotations

from cloudspend.config import Settings
from cloudspend.models.canonical import CloudResource
from cloudspend.models.recommendations import Evidence, Recommendation
from cloudspend.optimizer.common import metric, observation_days
from cloudspend.optimizer.pricing import monthly_equivalent

RULE_ID = "EC2-IDLE-001"
RULE_VERSION = "1.0"


def evaluate(resource: CloudResource, settings: Settings) -> Recommendation | None:
    if resource.resource_type != "ec2_instance" or resource.state.lower() != "running":
        return None
    cpu = metric(resource, "CPUUtilization")
    if not cpu or cpu.avg is None:
        return None
    p95_or_max = cpu.p95 if cpu.p95 is not None else cpu.max
    if p95_or_max is None:
        return None
    if cpu.avg >= settings.idle_cpu_avg_threshold or p95_or_max >= settings.idle_cpu_p95_threshold:
        return None
    if cpu.max is not None and cpu.max >= settings.idle_cpu_p95_threshold:
        return None
    if cpu.burst_score is not None and cpu.burst_score >= 5 and (cpu.max or 0) >= 15:
        return None

    days = observation_days(resource)
    if days is None or days < 7:
        return None

    net_in = metric(resource, "NetworkIn")
    net_out = metric(resource, "NetworkOut")
    network_avg = None
    if net_in and net_in.avg is not None or net_out and net_out.avg is not None:
        network_avg = (net_in.avg if net_in and net_in.avg is not None else 0) + (net_out.avg if net_out and net_out.avg is not None else 0)
        if network_avg >= settings.idle_network_avg_bytes_threshold:
            return None

    missing: list[str] = []
    confidence = "high"
    if metric(resource, "mem_used_percent") is None and metric(resource, "MemoryUtilization") is None:
        missing.append("memory utilization")
        confidence = "medium"
    if network_avg is None:
        missing.append("network utilization")
        confidence = "low" if confidence == "medium" else "medium"
    if days < settings.default_observation_days - 1:
        confidence = "medium"

    current_cost, basis = monthly_equivalent(resource.costs)
    savings = current_cost
    evidence = [
        Evidence(key="state", value=resource.state, threshold="running"),
        Evidence(key="cpu_avg_percent", value=cpu.avg, threshold=f"< {settings.idle_cpu_avg_threshold}"),
        Evidence(key="cpu_p95_or_max_percent", value=p95_or_max, threshold=f"< {settings.idle_cpu_p95_threshold}"),
        Evidence(key="observation_days", value=round(days, 1) if days is not None else "unknown", threshold=">= 7 days"),
        Evidence(key="network_avg_bytes", value=round(network_avg, 2) if network_avg is not None else "unknown", threshold=f"< {settings.idle_network_avg_bytes_threshold}"),
    ]
    return Recommendation(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        category="idle",
        resource_id=resource.resource_id,
        title="Idle EC2 candidate",
        suggested_action="Review whether this instance can be stopped, scheduled, or terminated after owner validation.",
        confidence=confidence,
        evidence=evidence,
        missing_signals=missing,
        current_monthly_cost=current_cost,
        estimated_monthly_savings=savings,
        savings_basis=basis,
    )

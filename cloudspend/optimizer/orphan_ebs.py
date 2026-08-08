from __future__ import annotations

from cloudspend.config import Settings
from cloudspend.models.canonical import CloudResource
from cloudspend.models.recommendations import Evidence, Recommendation
from cloudspend.optimizer.common import age_days
from cloudspend.optimizer.pricing import monthly_equivalent

RULE_ID = "EBS-ORPHAN-001"
RULE_VERSION = "1.0"


def evaluate(resource: CloudResource, settings: Settings) -> Recommendation | None:
    if resource.resource_type != "ebs_volume" or not resource.ebs:
        return None
    unattached = resource.state.lower() == "available" or not resource.ebs.attachments
    if not unattached:
        return None
    age = age_days(resource.ebs.create_time, resource.discovered_at)
    if age is None or age <= settings.orphan_ebs_min_age_days:
        return None
    confidence = "high" if resource.state.lower() == "available" else "medium"
    missing: list[str] = []
    current_cost, basis = monthly_equivalent(resource.costs)
    return Recommendation(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        category="orphan_storage",
        resource_id=resource.resource_id,
        title="Unattached EBS volume candidate",
        suggested_action="Review ownership and recovery requirements; consider snapshotting and deleting only after human approval.",
        confidence=confidence,
        evidence=[
            Evidence(key="state", value=resource.state, threshold="available or no attachments"),
            Evidence(key="attachments", value=resource.ebs.attachments or []),
            Evidence(key="age_days", value=round(age, 1) if age is not None else "unknown", threshold=f"> {settings.orphan_ebs_min_age_days}"),
            Evidence(key="size_gib", value=resource.ebs.size_gib),
            Evidence(key="encrypted", value=resource.ebs.encrypted),
            Evidence(key="volume_type", value=resource.ebs.volume_type),
        ],
        missing_signals=missing,
        current_monthly_cost=current_cost,
        estimated_monthly_savings=current_cost,
        savings_basis=basis,
    )

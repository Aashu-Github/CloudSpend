from __future__ import annotations

from decimal import Decimal

from cloudspend.config import Settings
from cloudspend.models.canonical import CloudResource
from cloudspend.models.recommendations import Evidence, Recommendation
from cloudspend.optimizer.pricing import monthly_equivalent

RULE_ID = "COST-ANOMALY-001"
RULE_VERSION = "1.0"


def evaluate(resource: CloudResource, settings: Settings) -> Recommendation | None:
    days = sorted(resource.costs.daily_costs.items())
    if len(days) < 8:
        return None
    current_day, current = days[-1]
    history = [value for _, value in days[-8:-1]]
    baseline = sum(history, Decimal("0")) / Decimal(len(history))
    if baseline <= 0:
        return None
    delta = current - baseline
    pct = delta / baseline * Decimal("100")
    if delta < Decimal(str(settings.anomaly_absolute_threshold)) or pct < Decimal(str(settings.anomaly_percent_threshold)):
        return None
    monthly, basis = monthly_equivalent(resource.costs)
    return Recommendation(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        category="anomaly",
        resource_id=resource.resource_id,
        title="Cost anomaly detected",
        suggested_action="Review recent deployment, traffic, pricing, and usage changes. CloudSpend does not infer a root cause from cost movement alone.",
        confidence="high" if len(days) >= 14 else "medium",
        evidence=[
            Evidence(key="anomaly_date", value=current_day.isoformat()),
            Evidence(key="latest_daily_cost", value=str(current)),
            Evidence(key="rolling_7d_baseline", value=str(baseline.quantize(Decimal('0.01')))),
            Evidence(key="absolute_increase", value=str(delta.quantize(Decimal('0.01'))), threshold=f">= ${settings.anomaly_absolute_threshold}"),
            Evidence(key="percent_increase", value=round(float(pct), 1), threshold=f">= {settings.anomaly_percent_threshold}%"),
        ],
        current_monthly_cost=monthly,
        estimated_monthly_savings=None,
        savings_basis=basis,
        safety_note="This is an alert, not a root-cause determination or automatic remediation recommendation.",
    )

from __future__ import annotations

from decimal import Decimal

from cloudspend.models.canonical import CloudResource, CostSummary

# Small, clearly labeled local pricing snapshot for demo/estimation purposes.
# Values are illustrative on-demand Linux hourly rates aligned to a common us-east-1 baseline,
# not a substitute for AWS Pricing API or a customer bill.
EC2_HOURLY_US_EAST_1 = {
    "t3.nano": Decimal("0.0052"),
    "t3.micro": Decimal("0.0104"),
    "t3.small": Decimal("0.0208"),
    "t3.medium": Decimal("0.0416"),
    "t3.large": Decimal("0.0832"),
    "t3.xlarge": Decimal("0.1664"),
    "t3.2xlarge": Decimal("0.3328"),
    "t4g.nano": Decimal("0.0042"),
    "t4g.micro": Decimal("0.0084"),
    "t4g.small": Decimal("0.0168"),
    "t4g.medium": Decimal("0.0336"),
    "t4g.large": Decimal("0.0672"),
    "m5.large": Decimal("0.096"),
    "m5.xlarge": Decimal("0.192"),
    "m5.2xlarge": Decimal("0.384"),
}
EBS_GIB_MONTH_US_EAST_1 = {"gp3": Decimal("0.08"), "gp2": Decimal("0.10"), "st1": Decimal("0.045"), "sc1": Decimal("0.015")}
GP3_INCLUDED_IOPS = 3000
GP3_INCLUDED_THROUGHPUT = 125
GP3_EXTRA_IOPS_MONTH = Decimal("0.005")
GP3_EXTRA_THROUGHPUT_MONTH = Decimal("0.04")
DOWNSIZE = {
    "t3.2xlarge": "t3.xlarge",
    "t3.xlarge": "t3.large",
    "t3.large": "t3.medium",
    "t3.medium": "t3.small",
    "t3.small": "t3.micro",
    "t3.micro": "t3.nano",
    "t4g.large": "t4g.medium",
    "t4g.medium": "t4g.small",
    "t4g.small": "t4g.micro",
    "t4g.micro": "t4g.nano",
    "m5.2xlarge": "m5.xlarge",
    "m5.xlarge": "m5.large",
}


def estimate_monthly_resource_cost(resource: CloudResource) -> Decimal | None:
    # The bundled pricing snapshot intentionally covers us-east-1 only. Other regions remain unavailable
    # rather than being mislabeled with a price from the wrong region.
    if resource.region != "us-east-1":
        return None
    if resource.resource_type == "ec2_instance" and resource.ec2:
        rate = EC2_HOURLY_US_EAST_1.get(resource.ec2.instance_type)
        if rate is None:
            return None
        return (rate * Decimal("730")).quantize(Decimal("0.01"))
    if resource.resource_type == "ebs_volume" and resource.ebs:
        rate = EBS_GIB_MONTH_US_EAST_1.get(resource.ebs.volume_type)
        if rate is None:
            return None
        monthly = Decimal(resource.ebs.size_gib) * rate
        if resource.ebs.volume_type == "gp3":
            if resource.ebs.iops is not None and resource.ebs.iops > GP3_INCLUDED_IOPS:
                monthly += Decimal(resource.ebs.iops - GP3_INCLUDED_IOPS) * GP3_EXTRA_IOPS_MONTH
            if resource.ebs.throughput is not None and resource.ebs.throughput > GP3_INCLUDED_THROUGHPUT:
                monthly += Decimal(resource.ebs.throughput - GP3_INCLUDED_THROUGHPUT) * GP3_EXTRA_THROUGHPUT_MONTH
        return monthly.quantize(Decimal("0.01"))
    return None


def monthly_equivalent(costs: CostSummary) -> tuple[Decimal | None, str]:
    value, basis = costs.best_monthly_cost()
    if value is None:
        return None, basis
    if costs.period_start and costs.period_end:
        days = max(1, (costs.period_end - costs.period_start).days + 1)
        if days < 27:
            value = (value / Decimal(days) * Decimal("30.4375")).quantize(Decimal("0.01"))
    return value.quantize(Decimal("0.01")), basis


def ensure_estimated_cost(resource: CloudResource) -> None:
    if resource.costs.best_monthly_cost()[0] is not None:
        return
    estimate = estimate_monthly_resource_cost(resource)
    if estimate is not None:
        resource.costs.estimated_resource_cost = estimate
        resource.costs.source = "local_pricing_snapshot_estimate"
        resource.costs.confidence = "low"


def downsize_savings(resource: CloudResource) -> tuple[str | None, Decimal | None]:
    if not resource.ec2:
        return None, None
    current_type = resource.ec2.instance_type
    target = DOWNSIZE.get(current_type)
    if target is None:
        return None, None
    if resource.region != "us-east-1":
        return target, None
    current_rate = EC2_HOURLY_US_EAST_1.get(current_type)
    target_rate = EC2_HOURLY_US_EAST_1.get(target)
    if current_rate is None or target_rate is None:
        return target, None
    savings = (current_rate - target_rate) * Decimal("730")
    return target, max(Decimal("0"), savings.quantize(Decimal("0.01")))

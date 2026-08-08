from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cloudspend.ai.fixture_generator import generate_deterministic_bundle
from cloudspend.config import Settings
from cloudspend.ingestion.normalize import normalize_bundle
from cloudspend.optimizer.engine import optimize
from cloudspend.optimizer.pricing import ensure_estimated_cost
from cloudspend.storage import ScanStore


def test_estimated_cost_is_explicitly_labeled():
    resources = normalize_bundle(generate_deterministic_bundle(instance_count=4, seed=12))
    resource = next(r for r in resources if r.resource_type == "ec2_instance")
    resource.costs.actual_resource_cost = None
    resource.costs.allocated_cost = None
    resource.costs.estimated_resource_cost = None
    resource.costs.source = "unavailable"
    ensure_estimated_cost(resource)
    assert resource.costs.actual_resource_cost is None
    assert resource.costs.estimated_resource_cost is not None
    assert "estimate" in resource.costs.source


def test_sqlite_scan_roundtrip(tmp_path: Path):
    resources = normalize_bundle(generate_deterministic_bundle(instance_count=4, seed=3))
    result = optimize(resources, Settings())
    store = ScanStore(f"sqlite:///{tmp_path / 'cloudspend.db'}")
    scan_id = store.save_scan(result, "demo", {"scenario": "test"}, ["warning"], [])
    loaded = store.get_scan(scan_id)
    assert loaded is not None
    assert loaded["source_mode"] == "demo"
    assert len(loaded["resources"]) == len(result.resources)
    assert len(loaded["recommendations"]) == len(result.recommendations)
    assert loaded["warnings"] == ["warning"]


def test_total_savings_does_not_double_count_same_resource():
    resources = normalize_bundle(generate_deterministic_bundle(instance_count=4, seed=42))
    result = optimize(resources, Settings())
    expected = {}
    for rec in result.recommendations:
        if rec.estimated_monthly_savings is not None:
            expected[rec.resource_id] = max(expected.get(rec.resource_id, Decimal("0")), rec.estimated_monthly_savings)
    assert result.potential_savings == sum(expected.values(), Decimal("0")).quantize(Decimal("0.01"))


def test_orphan_rule_requires_volume_age_evidence():
    resources = normalize_bundle(generate_deterministic_bundle(instance_count=4, volume_count=1, seed=8))
    volume = next(r for r in resources if r.resource_type == "ebs_volume")
    volume.ebs.create_time = None
    recs = [r for r in optimize(resources, Settings()).recommendations if r.resource_id == volume.resource_id]
    assert all(rec.category != "orphan_storage" for rec in recs)


def test_gp3_estimate_includes_provisioned_iops_and_throughput_extras():
    from cloudspend.models.canonical import CloudResource, EBSDetails, SourceLineage
    from cloudspend.optimizer.pricing import estimate_monthly_resource_cost

    resource = CloudResource(
        region="us-east-1",
        resource_type="ebs_volume",
        resource_id="vol-0123456789abcdef0",
        state="available",
        source_lineage=SourceLineage(provider_mode="demo", source_name="test"),
        ebs=EBSDetails(size_gib=100, volume_type="gp3", iops=5000, throughput=225),
    )
    # 100 GiB * $0.08 + 2,000 extra IOPS * $0.005 + 100 extra MB/s * $0.04
    assert estimate_monthly_resource_cost(resource) == Decimal("22.00")


def test_local_price_snapshot_does_not_reuse_us_east_1_rate_for_other_regions():
    from cloudspend.models.canonical import CloudResource, EC2Details, SourceLineage
    from cloudspend.optimizer.pricing import estimate_monthly_resource_cost

    resource = CloudResource(
        region="eu-west-1",
        resource_type="ec2_instance",
        resource_id="i-0123456789abcdef0",
        state="running",
        source_lineage=SourceLineage(provider_mode="demo", source_name="test"),
        ec2=EC2Details(instance_type="t3.large"),
    )
    assert estimate_monthly_resource_cost(resource) is None

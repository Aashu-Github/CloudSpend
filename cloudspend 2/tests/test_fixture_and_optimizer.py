from __future__ import annotations

from copy import deepcopy

import pytest

from cloudspend.ai.fixture_generator import generate_deterministic_bundle, validate_fixture_bundle
from cloudspend.config import Settings
from cloudspend.ingestion.normalize import normalize_bundle
from cloudspend.ingestion.validators import validate_bundle_consistency
from cloudspend.optimizer.engine import optimize


def test_deterministic_fixture_is_reproducible_and_consistent():
    first = generate_deterministic_bundle(instance_count=12, seed=42)
    second = generate_deterministic_bundle(instance_count=12, seed=42)
    assert first == second
    assert validate_bundle_consistency(first) == []
    validate_fixture_bundle(first)


def test_mixed_fixture_yields_expected_categories_and_keep_resource():
    resources = normalize_bundle(generate_deterministic_bundle(instance_count=12, seed=42))
    result = optimize(resources, Settings())
    categories = {rec.category for rec in result.recommendations}
    assert {"idle", "rightsize", "schedule", "orphan_storage", "anomaly"}.issubset(categories)
    flagged = {rec.resource_id for rec in result.recommendations}
    assert any(resource.resource_id not in flagged for resource in resources)
    for rec in result.recommendations:
        assert rec.rule_id
        assert rec.rule_version
        assert rec.evidence
        assert rec.confidence in {"high", "medium", "low"}
        assert "review" in (rec.suggested_action + " " + rec.safety_note).lower() or rec.category == "anomaly"


def test_bursty_resource_is_not_idle():
    bundle = generate_deterministic_bundle(instance_count=8, seed=42)
    resources = normalize_bundle(bundle)
    bursty = next(r for r in resources if r.tags.get("CloudSpendScenario") == "bursty")
    recs = [r for r in optimize(resources, Settings()).recommendations if r.resource_id == bursty.resource_id]
    assert all(rec.category != "idle" for rec in recs)


def test_missing_memory_lowers_idle_confidence_not_usage_value():
    resources = normalize_bundle(generate_deterministic_bundle(instance_count=8, seed=42))
    idle_resource = next(r for r in resources if r.tags.get("CloudSpendScenario") == "idle")
    assert "mem_used_percent" not in idle_resource.metrics
    idle_rec = next(r for r in optimize(resources, Settings()).recommendations if r.resource_id == idle_resource.resource_id and r.category == "idle")
    assert idle_rec.confidence in {"medium", "low"}
    assert "memory utilization" in idle_rec.missing_signals


def test_invalid_cross_file_reference_is_rejected():
    bundle = generate_deterministic_bundle(instance_count=6, seed=4)
    broken = deepcopy(bundle)
    first_query = next(iter(broken["manifest.json"]["metric_queries"].values()))
    first_query["resource_id"] = "i-fffffffffffffffff"
    errors = validate_bundle_consistency(broken)
    assert any("unknown instance" in e for e in errors)
    with pytest.raises(ValueError):
        validate_fixture_bundle(broken)


def test_idle_rule_requires_at_least_seven_days_of_timestamps():
    bundle = generate_deterministic_bundle(instance_count=4, window_days=4, seed=42)
    resources = normalize_bundle(bundle)
    idle_resource = next(r for r in resources if r.tags.get("CloudSpendScenario") == "idle")
    recs = [r for r in optimize(resources, Settings()).recommendations if r.resource_id == idle_resource.resource_id]
    assert all(rec.category != "idle" for rec in recs)

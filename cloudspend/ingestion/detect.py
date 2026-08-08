from __future__ import annotations

from typing import Any

CANONICAL_REQUIRED = {"resource_type", "resource_id", "source_lineage"}


def detect_json_family(payload: Any) -> str:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        if CANONICAL_REQUIRED.issubset(payload[0].keys()):
            return "canonical_list"
    if not isinstance(payload, dict):
        return "unknown"
    if "resources" in payload and isinstance(payload["resources"], list):
        if not payload["resources"] or CANONICAL_REQUIRED.issubset(payload["resources"][0].keys()):
            return "canonical_bundle"
    if CANONICAL_REQUIRED.issubset(payload.keys()):
        return "canonical_resource"
    if "Reservations" in payload:
        return "ec2_describe_instances"
    if "Volumes" in payload:
        return "ec2_describe_volumes"
    if "MetricDataResults" in payload:
        return "cloudwatch_get_metric_data"
    if "ResultsByTime" in payload:
        return "cost_explorer"
    if "bundle_version" in payload and "files" in payload:
        return "manifest"
    return "unknown"


def detect_tabular_family(columns: list[str]) -> str:
    normalized = {c.strip().lower().replace("/", "_").replace(" ", "_") for c in columns}
    if {"resource_id", "resource_type"}.issubset(normalized):
        return "canonical_tabular"
    cur_markers = {
        "line_item_resource_id",
        "lineitem_resourceid",
        "line_item_unblended_cost",
        "lineitem_unblendedcost",
    }
    if len(normalized & cur_markers) >= 2:
        return "cur_like"
    return "unknown"

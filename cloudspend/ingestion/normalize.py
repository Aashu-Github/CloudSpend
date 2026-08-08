from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from cloudspend.ingestion.detect import detect_json_family, detect_tabular_family
from cloudspend.models.canonical import (
    CloudResource,
    CostSummary,
    EBSDetails,
    EC2Details,
    MetricSummary,
    SourceLineage,
)

_INSTANCE_RE = re.compile(r"i-[0-9a-fA-F]{8,17}")
_VOLUME_RE = re.compile(r"vol-[0-9a-fA-F]{8,17}")


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "nan"):
        return None
    try:
        d = Decimal(str(value))
        return d if d >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _tags(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        result: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict) and item.get("Key") is not None:
                result[str(item["Key"])] = str(item.get("Value", ""))
        return result
    return {}


def _metric_summary(metric_name: str, namespace: str, unit: str | None, timestamps: list[Any], values: list[Any]) -> MetricSummary:
    pairs: list[tuple[datetime, float]] = []
    for raw_ts, raw_val in zip(timestamps, values, strict=False):
        ts = parse_datetime(raw_ts)
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            continue
        if ts is not None and math.isfinite(val):
            pairs.append((ts, val))
    pairs.sort(key=lambda item: item[0])
    clean_values = [p[1] for p in pairs]
    clean_timestamps = [p[0] for p in pairs]
    if not clean_values:
        return MetricSummary(namespace=namespace, metric_name=metric_name, unit=unit, missing_ratio=1.0)
    ordered = sorted(clean_values)
    p95_index = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    avg = sum(clean_values) / len(clean_values)
    max_v = max(clean_values)
    p95 = ordered[p95_index]
    burst_score = None
    if avg > 0:
        burst_score = max_v / max(avg, 0.001)
    return MetricSummary(
        namespace=namespace,
        metric_name=metric_name,
        unit=unit,
        avg=round(avg, 4),
        p95=round(p95, 4),
        max=round(max_v, 4),
        min=round(min(clean_values), 4),
        samples=len(clean_values),
        missing_ratio=0.0,
        burst_score=round(burst_score, 4) if burst_score is not None else None,
        timestamps=clean_timestamps,
        values=clean_values,
    )


def _extract_resource_id(value: str) -> str | None:
    match = _INSTANCE_RE.search(value)
    if match:
        return match.group(0)
    match = _VOLUME_RE.search(value)
    return match.group(0) if match else None


def normalize_bundle(payloads: dict[str, Any], mode: str = "demo", source_name: str = "bundle") -> list[CloudResource]:
    manifest = payloads.get("manifest.json") or {}
    account_id = manifest.get("account_id")
    regions = manifest.get("regions") or ["unknown"]
    default_region = regions[0] if regions else "unknown"
    discovered_at = parse_datetime(manifest.get("generated_at")) or datetime.now(timezone.utc)
    lineage = SourceLineage(provider_mode=mode, source_name=source_name, source_family="cloudspend_bundle")

    resources: dict[str, CloudResource] = {}
    ec2_payload = payloads.get("ec2_describe_instances.json") or {}
    for reservation in ec2_payload.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            rid = instance.get("InstanceId")
            if not rid:
                continue
            tags = _tags(instance.get("Tags", []))
            placement = instance.get("Placement") or {}
            az = placement.get("AvailabilityZone")
            region = instance.get("Region") or (az[:-1] if isinstance(az, str) and len(az) > 1 else default_region)
            known = {
                "InstanceId", "InstanceType", "State", "LaunchTime", "Tags", "Placement", "PlatformDetails",
                "Architecture", "VpcId", "PrivateIpAddress", "Region",
            }
            resources[rid] = CloudResource(
                account_id=account_id,
                region=region,
                resource_type="ec2_instance",
                resource_id=rid,
                name=tags.get("Name"),
                state=(instance.get("State") or {}).get("Name", "unknown"),
                tags=tags,
                discovered_at=discovered_at,
                source_lineage=lineage,
                ec2=EC2Details(
                    instance_type=instance.get("InstanceType", "unknown"),
                    launch_time=parse_datetime(instance.get("LaunchTime")),
                    availability_zone=az,
                    platform=instance.get("PlatformDetails"),
                    architecture=instance.get("Architecture"),
                    vpc_id=instance.get("VpcId"),
                    private_ip=instance.get("PrivateIpAddress"),
                    schedule_eligible=str(tags.get("CloudSpendScheduleEligible", "false")).lower() in {"1", "true", "yes"},
                ),
                source_metadata={k: v for k, v in instance.items() if k not in known},
            )

    ebs_payload = payloads.get("ec2_describe_volumes.json") or {}
    for volume in ebs_payload.get("Volumes", []):
        rid = volume.get("VolumeId")
        if not rid:
            continue
        attachments = [a.get("InstanceId") for a in volume.get("Attachments", []) if a.get("InstanceId")]
        tags = _tags(volume.get("Tags", []))
        az = volume.get("AvailabilityZone")
        region = volume.get("Region") or (az[:-1] if isinstance(az, str) and len(az) > 1 else default_region)
        known = {
            "VolumeId", "Size", "VolumeType", "State", "Attachments", "CreateTime", "Encrypted", "Tags",
            "AvailabilityZone", "Iops", "Throughput", "Region",
        }
        resources[rid] = CloudResource(
            account_id=account_id,
            region=region,
            resource_type="ebs_volume",
            resource_id=rid,
            name=tags.get("Name"),
            state=volume.get("State", "unknown"),
            tags=tags,
            discovered_at=discovered_at,
            source_lineage=lineage,
            ebs=EBSDetails(
                size_gib=int(volume.get("Size") or 0),
                volume_type=volume.get("VolumeType", "gp3"),
                encrypted=volume.get("Encrypted"),
                create_time=parse_datetime(volume.get("CreateTime")),
                attachments=attachments,
                iops=volume.get("Iops"),
                throughput=volume.get("Throughput"),
            ),
            source_metadata={k: v for k, v in volume.items() if k not in known},
        )

    metric_map = manifest.get("metric_queries", {})
    cw_payload = payloads.get("cloudwatch_get_metric_data.json") or {}
    for result in cw_payload.get("MetricDataResults", []):
        query_id = result.get("Id", "")
        mapping = metric_map.get(query_id, {})
        rid = mapping.get("resource_id") or _extract_resource_id(str(result.get("Label", "")))
        if not rid or rid not in resources:
            continue
        metric_name = mapping.get("metric_name") or result.get("MetricName") or str(result.get("Label", query_id)).split()[-1]
        namespace = mapping.get("namespace", "AWS/EC2")
        unit = mapping.get("unit") or result.get("Unit")
        resources[rid].metrics[metric_name] = _metric_summary(
            metric_name,
            namespace,
            unit,
            result.get("Timestamps") or [],
            result.get("Values") or [],
        )

    ce_payload = payloads.get("cost_explorer_get_cost_and_usage_with_resources.json") or {}
    daily_by_resource: dict[str, dict[date, Decimal]] = {}
    for period in ce_payload.get("ResultsByTime", []):
        start_raw = (period.get("TimePeriod") or {}).get("Start")
        try:
            day = date.fromisoformat(start_raw) if start_raw else None
        except ValueError:
            day = None
        for group in period.get("Groups", []):
            keys = group.get("Keys") or []
            rid = next((_extract_resource_id(str(k)) for k in keys if _extract_resource_id(str(k))), None)
            if not rid or rid not in resources:
                continue
            metric = (group.get("Metrics") or {}).get("UnblendedCost") or (group.get("Metrics") or {}).get("NetUnblendedCost") or {}
            amount = _decimal(metric.get("Amount"))
            if amount is None:
                continue
            if day:
                daily_by_resource.setdefault(rid, {})[day] = amount
    for rid, days in daily_by_resource.items():
        total = sum(days.values(), Decimal("0"))
        period_start = min(days) if days else None
        period_end = max(days) if days else None
        resources[rid].costs = CostSummary(
            actual_resource_cost=total,
            period_start=period_start,
            period_end=period_end,
            source="aws_cost_explorer_resource_level",
            confidence="high",
            daily_costs=days,
        )

    return list(resources.values())


def normalize_standalone_json(payload: Any, family: str, source_name: str = "upload.json") -> list[CloudResource]:
    if family in {"canonical_resource", "canonical_list", "canonical_bundle"}:
        if family == "canonical_resource":
            raw_resources = [payload]
        elif family == "canonical_list":
            raw_resources = payload
        else:
            raw_resources = payload.get("resources", [])
        result: list[CloudResource] = []
        canonical_fields = set(CloudResource.model_fields)
        for raw in raw_resources:
            item = dict(raw)
            extras = {k: v for k, v in item.items() if k not in canonical_fields}
            for key in extras:
                item.pop(key, None)
            metadata = dict(item.get("source_metadata") or {})
            metadata.update(extras)
            item["source_metadata"] = metadata
            if isinstance(item.get("source_lineage"), dict):
                item["source_lineage"] = dict(item["source_lineage"])
                item["source_lineage"]["provider_mode"] = "canonical"
            result.append(CloudResource.model_validate(item))
        return result

    filename_map = {
        "ec2_describe_instances": "ec2_describe_instances.json",
        "ec2_describe_volumes": "ec2_describe_volumes.json",
        "cloudwatch_get_metric_data": "cloudwatch_get_metric_data.json",
        "cost_explorer": "cost_explorer_get_cost_and_usage_with_resources.json",
    }
    pseudo = {
        "manifest.json": {
            "bundle_version": "partial-1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "regions": ["unknown"],
            "metric_queries": {},
        },
        filename_map[family]: payload,
    }
    return normalize_bundle(pseudo, mode="file", source_name=source_name)


def _normalized_columns(df: pd.DataFrame) -> dict[str, str]:
    return {str(c).strip().lower().replace("/", "_").replace(" ", "_"): str(c) for c in df.columns}


def normalize_tabular(df: pd.DataFrame, source_name: str, family: str | None = None) -> list[CloudResource]:
    family = family or detect_tabular_family([str(c) for c in df.columns])
    cols = _normalized_columns(df)
    lineage = SourceLineage(provider_mode="file" if family != "cur_like" else "cur", source_name=source_name, source_family=family)
    if family == "canonical_tabular":
        out: list[CloudResource] = []
        for _, row in df.fillna("").iterrows():
            rid = str(row[cols["resource_id"]])
            rtype = str(row[cols["resource_type"]]).strip().lower()
            region = str(row[cols.get("region", cols["resource_id"])]) if "region" in cols else "unknown"
            state = str(row[cols.get("state", cols["resource_id"])]) if "state" in cols else "unknown"
            name = str(row[cols["name"]]) if "name" in cols and row[cols["name"]] != "" else None
            tags: dict[str, str] = {}
            env_col = cols.get("environment")
            if env_col and row[env_col] != "":
                tags["Environment"] = str(row[env_col])
            actual = _decimal(row[cols["actual_resource_cost"]]) if "actual_resource_cost" in cols else None
            allocated = _decimal(row[cols["allocated_cost"]]) if "allocated_cost" in cols else None
            estimated = _decimal(row[cols["estimated_resource_cost"]]) if "estimated_resource_cost" in cols else None
            metrics: dict[str, MetricSummary] = {}
            if "cpu_avg" in cols or "cpu_p95" in cols:
                cpu_avg = float(row[cols["cpu_avg"]]) if "cpu_avg" in cols and row[cols["cpu_avg"]] != "" else None
                cpu_p95 = float(row[cols["cpu_p95"]]) if "cpu_p95" in cols and row[cols["cpu_p95"]] != "" else None
                cpu_max = float(row[cols["cpu_max"]]) if "cpu_max" in cols and row[cols["cpu_max"]] != "" else cpu_p95
                metrics["CPUUtilization"] = MetricSummary(metric_name="CPUUtilization", unit="Percent", avg=cpu_avg, p95=cpu_p95, max=cpu_max, samples=1 if cpu_avg is not None else 0)
            if rtype == "ec2_instance":
                instance_type = str(row[cols["instance_type"]]) if "instance_type" in cols else "unknown"
                resource = CloudResource(
                    region=region, resource_type="ec2_instance", resource_id=rid, name=name, state=state, tags=tags,
                    source_lineage=lineage, ec2=EC2Details(instance_type=instance_type), metrics=metrics,
                    costs=CostSummary(actual_resource_cost=actual, allocated_cost=allocated, estimated_resource_cost=estimated, source="canonical_tabular", confidence="medium"),
                )
            elif rtype == "ebs_volume":
                size = int(float(row[cols["size_gib"]])) if "size_gib" in cols and row[cols["size_gib"]] != "" else 0
                resource = CloudResource(
                    region=region, resource_type="ebs_volume", resource_id=rid, name=name, state=state, tags=tags,
                    source_lineage=lineage, ebs=EBSDetails(size_gib=size),
                    costs=CostSummary(actual_resource_cost=actual, allocated_cost=allocated, estimated_resource_cost=estimated, source="canonical_tabular", confidence="medium"),
                )
            else:
                continue
            known_semantic = {
                "resource_id", "resource_type", "region", "state", "name", "environment",
                "actual_resource_cost", "allocated_cost", "estimated_resource_cost",
                "cpu_avg", "cpu_p95", "cpu_max", "instance_type", "size_gib",
            }
            known_original = {cols[key] for key in known_semantic if key in cols}
            resource.source_metadata = {
                str(k): (None if pd.isna(v) else v)
                for k, v in row.to_dict().items()
                if k not in known_original
            }
            out.append(resource)
        return out

    if family == "cur_like":
        rid_col = cols.get("line_item_resource_id") or cols.get("lineitem_resourceid")
        cost_col = cols.get("line_item_unblended_cost") or cols.get("lineitem_unblendedcost")
        if not rid_col or not cost_col:
            return []
        region_col = cols.get("product_region") or cols.get("region")
        product_col = cols.get("line_item_product_code") or cols.get("lineitem_productcode") or cols.get("product_product_name")
        grouped = df.groupby(rid_col, dropna=True)
        out = []
        for rid_value, group in grouped:
            rid = str(rid_value)
            if not rid or rid == "nan":
                continue
            total = sum((_decimal(v) or Decimal("0") for v in group[cost_col]), Decimal("0"))
            region = str(group.iloc[0][region_col]) if region_col and pd.notna(group.iloc[0][region_col]) else "unknown"
            product = str(group.iloc[0][product_col]) if product_col and pd.notna(group.iloc[0][product_col]) else ""
            if rid.startswith("i-") or "EC2" in product.upper():
                out.append(CloudResource(
                    region=region, resource_type="ec2_instance", resource_id=rid, state="unknown", source_lineage=lineage,
                    ec2=EC2Details(instance_type="unknown"),
                    costs=CostSummary(allocated_cost=total, source="cur_like_unblended_cost", confidence="medium"),
                    source_metadata={"partial_inventory": True, "product": product},
                ))
            elif rid.startswith("vol-") or "EBS" in product.upper():
                out.append(CloudResource(
                    region=region, resource_type="ebs_volume", resource_id=rid, state="unknown", source_lineage=lineage,
                    ebs=EBSDetails(size_gib=0),
                    costs=CostSummary(allocated_cost=total, source="cur_like_unblended_cost", confidence="medium"),
                    source_metadata={"partial_inventory": True, "product": product},
                ))
        return out
    return []


def normalize_any(payload: Any, source_name: str = "source") -> list[CloudResource]:
    if isinstance(payload, pd.DataFrame):
        return normalize_tabular(payload, source_name)
    family = detect_json_family(payload)
    if family == "unknown" or family == "manifest":
        return []
    return normalize_standalone_json(payload, family, source_name)

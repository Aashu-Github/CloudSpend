from __future__ import annotations

import json
import random
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from cloudspend.ai.prompts import FIXTURE_SYSTEM_PROMPT, FIXTURE_USER_TEMPLATE
from cloudspend.ai.provider import AIProvider
from cloudspend.ingestion.normalize import normalize_bundle
from cloudspend.ingestion.validators import validate_bundle_consistency
from cloudspend.optimizer.pricing import EC2_HOURLY_US_EAST_1

FILE_KEYS = {
    "manifest": "manifest.json",
    "ec2_describe_instances": "ec2_describe_instances.json",
    "ec2_describe_volumes": "ec2_describe_volumes.json",
    "cloudwatch_get_metric_data": "cloudwatch_get_metric_data.json",
    "cost_explorer_get_cost_and_usage_with_resources": "cost_explorer_get_cost_and_usage_with_resources.json",
}


def _hex(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def _instance_id(rng: random.Random) -> str:
    return "i-" + _hex(rng, 17)


def _volume_id(rng: random.Random) -> str:
    return "vol-" + _hex(rng, 17)


def _metric_series(pattern: str, start: datetime, days: int, rng: random.Random) -> tuple[list[str], list[float]]:
    timestamps: list[str] = []
    values: list[float] = []
    steps = max(days * 4, 32)
    for index in range(steps):
        ts = start + timedelta(hours=6 * index)
        if ts > start + timedelta(days=days):
            break
        timestamps.append(ts.isoformat().replace("+00:00", "Z"))
        weekday = ts.weekday() < 5
        business = weekday and 8 <= ts.hour < 18
        if pattern == "idle":
            value = rng.uniform(0.7, 3.5)
        elif pattern == "rightsize":
            value = rng.uniform(7, 17)
        elif pattern == "schedule":
            value = rng.uniform(22, 42) if business else rng.uniform(0.2, 2.0)
        elif pattern == "bursty":
            value = rng.uniform(1, 5)
            if index % 9 == 0:
                value = rng.uniform(75, 94)
        else:
            value = rng.uniform(32, 67)
        values.append(round(value, 3))
    return timestamps, values


def _network_series(pattern: str, cpu_timestamps: list[str], rng: random.Random) -> list[float]:
    values = []
    for index, ts_raw in enumerate(cpu_timestamps):
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        business = ts.weekday() < 5 and 8 <= ts.hour < 18
        if pattern == "idle":
            value = rng.uniform(10_000, 150_000)
        elif pattern == "rightsize":
            value = rng.uniform(200_000, 2_000_000)
        elif pattern == "schedule":
            value = rng.uniform(1_000_000, 4_000_000) if business else rng.uniform(10_000, 80_000)
        elif pattern == "bursty":
            value = rng.uniform(20_000, 150_000) if index % 9 else rng.uniform(8_000_000, 20_000_000)
        else:
            value = rng.uniform(2_000_000, 10_000_000)
        values.append(round(value, 2))
    return values


def generate_deterministic_bundle(
    scenario: str = "mixed-fleet",
    instance_count: int = 12,
    volume_count: int | None = None,
    regions: list[str] | None = None,
    window_days: int = 14,
    seed: int = 42,
) -> dict[str, Any]:
    instance_count = max(1, int(instance_count))
    volume_count = max(0, int(volume_count if volume_count is not None else max(3, instance_count // 4)))
    regions = regions or ["us-east-1"]
    rng = random.Random(seed)
    # A fixed default anchor makes a seed reproducible byte-for-byte across runs.
    # Callers may regenerate source timestamps later by changing this implementation or supplying live data;
    # the demo generator intentionally favors repeatability.
    now = datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)
    start = now - timedelta(days=window_days)
    account_id = "000000000000"

    patterns = ["idle", "rightsize", "schedule", "bursty"] + ["steady"] * max(0, instance_count - 4)
    rng.shuffle(patterns[4:]) if len(patterns) > 4 else None
    types = ["t3.large", "t3.xlarge", "t3.medium", "m5.large", "t3.small"]

    instances = []
    metric_results = []
    metric_map: dict[str, Any] = {}
    costs_by_day: dict[str, list[dict[str, Any]]] = {}
    instance_ids: list[str] = []

    for idx in range(instance_count):
        rid = _instance_id(rng)
        instance_ids.append(rid)
        pattern = patterns[idx] if idx < len(patterns) else "steady"
        region = regions[idx % len(regions)]
        az = region + rng.choice(["a", "b", "c"])
        if pattern == "idle":
            env, name = "production", f"zombie-worker-{idx+1:02d}"
            instance_type = "t3.large"
        elif pattern == "rightsize":
            env, name = "production", f"api-low-util-{idx+1:02d}"
            instance_type = "t3.xlarge"
        elif pattern == "schedule":
            env, name = "development", f"dev-api-{idx+1:02d}"
            instance_type = "t3.large"
        elif pattern == "bursty":
            env, name = "production", f"batch-bursty-{idx+1:02d}"
            instance_type = "m5.large"
        else:
            env, name = "production", f"service-{idx+1:02d}"
            instance_type = rng.choice(types)

        instances.append({
            "InstanceId": rid,
            "InstanceType": instance_type,
            "State": {"Name": "running"},
            "LaunchTime": (start - timedelta(days=rng.randint(15, 120))).isoformat().replace("+00:00", "Z"),
            "Placement": {"AvailabilityZone": az},
            "Architecture": "x86_64",
            "VpcId": "vpc-" + _hex(rng, 17),
            "PrivateIpAddress": f"10.{idx // 240}.{(idx % 240) + 1}.10",
            "Tags": [
                {"Key": "Name", "Value": name},
                {"Key": "Environment", "Value": env},
                {"Key": "CloudSpendScenario", "Value": pattern},
            ],
        })
        cpu_ts, cpu_values = _metric_series(pattern, start, window_days, rng)
        for metric_idx, (metric_name, unit, values) in enumerate([
            ("CPUUtilization", "Percent", cpu_values),
            ("NetworkIn", "Bytes", _network_series(pattern, cpu_ts, rng)),
            ("NetworkOut", "Bytes", _network_series(pattern, cpu_ts, rng)),
        ]):
            qid = f"m{idx}_{metric_idx}"
            metric_map[qid] = {"resource_id": rid, "metric_name": metric_name, "namespace": "AWS/EC2", "unit": unit}
            metric_results.append({"Id": qid, "Label": f"{rid} {metric_name}", "Timestamps": cpu_ts, "Values": values, "StatusCode": "Complete"})

        if idx in {0, 1, 2, 4}:
            # Some resources have optional memory telemetry; the idle resource deliberately does not.
            if idx != 0:
                mem_values = [round(rng.uniform(12, 32), 2) for _ in cpu_ts]
                qid = f"mem{idx}"
                metric_map[qid] = {"resource_id": rid, "metric_name": "mem_used_percent", "namespace": "CWAgent", "unit": "Percent"}
                metric_results.append({"Id": qid, "Label": f"{rid} mem_used_percent", "Timestamps": cpu_ts, "Values": mem_values, "StatusCode": "Complete"})

        hourly = EC2_HOURLY_US_EAST_1.get(instance_type, Decimal("0.08"))
        daily_base = hourly * Decimal("24")
        for day_index in range(window_days):
            day = (start.date() + timedelta(days=day_index))
            noise = Decimal(str(rng.uniform(0.96, 1.04)))
            amount = (daily_base * noise).quantize(Decimal("0.0001"))
            if idx == min(4, instance_count - 1) and day_index == window_days - 1:
                amount = (daily_base * Decimal("4.2")).quantize(Decimal("0.0001"))
            costs_by_day.setdefault(day.isoformat(), []).append({
                "Keys": [rid],
                "Metrics": {"UnblendedCost": {"Amount": str(amount), "Unit": "USD"}},
            })

    volumes = []
    for idx in range(volume_count):
        rid = _volume_id(rng)
        orphan = idx == 0 or (idx == 1 and volume_count >= 5)
        region = regions[idx % len(regions)]
        create_time = now - timedelta(days=30 + idx * 3 if orphan else 10 + idx)
        attachments = [] if orphan else [{"InstanceId": instance_ids[idx % len(instance_ids)], "State": "attached", "Device": "/dev/xvda"}]
        volumes.append({
            "VolumeId": rid,
            "Size": [20, 50, 100, 200][idx % 4],
            "VolumeType": "gp3",
            "State": "available" if orphan else "in-use",
            "Attachments": attachments,
            "CreateTime": create_time.isoformat().replace("+00:00", "Z"),
            "Encrypted": idx % 3 != 0,
            "AvailabilityZone": region + "a",
            "Iops": 3000,
            "Throughput": 125,
            "Tags": [{"Key": "Name", "Value": f"{'orphan' if orphan else 'data'}-volume-{idx+1:02d}"}],
        })

    results_by_time = []
    for day, groups in sorted(costs_by_day.items()):
        end_day = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
        results_by_time.append({"TimePeriod": {"Start": day, "End": end_day}, "Total": {}, "Groups": groups, "Estimated": False})

    manifest = {
        "bundle_version": "1.0",
        "generator": "cloudspend-deterministic",
        "scenario": scenario,
        "seed": seed,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "account_id": account_id,
        "regions": regions,
        "window_start": start.isoformat().replace("+00:00", "Z"),
        "window_end": now.isoformat().replace("+00:00", "Z"),
        "files": {
            "instances": "ec2_describe_instances.json",
            "volumes": "ec2_describe_volumes.json",
            "metrics": "cloudwatch_get_metric_data.json",
            "costs": "cost_explorer_get_cost_and_usage_with_resources.json",
        },
        "metric_queries": metric_map,
    }
    return {
        "manifest.json": manifest,
        "ec2_describe_instances.json": {"Reservations": [{"ReservationId": "r-" + _hex(rng, 17), "Instances": instances}]},
        "ec2_describe_volumes.json": {"Volumes": volumes},
        "cloudwatch_get_metric_data.json": {"MetricDataResults": metric_results},
        "cost_explorer_get_cost_and_usage_with_resources.json": {
            "GroupDefinitions": [{"Type": "DIMENSION", "Key": "RESOURCE_ID"}],
            "ResultsByTime": results_by_time,
        },
    }


def generate_ai_bundle(
    provider: AIProvider,
    scenario: str,
    instance_count: int,
    volume_count: int,
    regions: list[str],
    window_days: int,
    seed: int,
) -> dict[str, Any]:
    user_prompt = FIXTURE_USER_TEMPLATE.format(
        scenario=scenario,
        instance_count=instance_count,
        volume_count=volume_count,
        regions=", ".join(regions),
        window_days=window_days,
        patterns="steady production, idle/zombie, low-utilization, bursty, and non-optimizable controls",
        seed=seed,
    )
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "mock_bundle.schema.json"
    if schema_path.exists():
        user_prompt += "\n\nSupplied JSON Schema for the logical ZIP wrapper:\n" + schema_path.read_text(encoding="utf-8")
    raw = provider.generate_json(FIXTURE_SYSTEM_PROMPT, user_prompt)
    if all(filename in raw for filename in FILE_KEYS.values()):
        payloads = {filename: raw[filename] for filename in FILE_KEYS.values()}
    else:
        payloads = {}
        for key, filename in FILE_KEYS.items():
            if key not in raw:
                raise ValueError(f"AI fixture output is missing required key: {key}")
            payloads[filename] = raw[key]
    validate_fixture_bundle(payloads, label="AI fixture")
    return payloads


def validate_fixture_bundle(payloads: dict[str, Any], label: str = "Fixture") -> None:
    errors = validate_bundle_consistency(payloads)
    if errors:
        raise ValueError(f"{label} consistency validation failed: " + " ".join(errors))
    # Normalization is the Pydantic validation gate used by the optimizer. If source data cannot
    # produce valid canonical objects, the generated bundle is rejected before persistence.
    try:
        resources = normalize_bundle(payloads, mode="demo", source_name="generated-fixture")
    except Exception as exc:
        raise ValueError(f"{label} failed canonical Pydantic validation: {exc}") from exc
    if not resources:
        raise ValueError(f"{label} did not produce any canonical resources.")


def write_bundle_zip(payloads: dict[str, Any], output_path: str | Path) -> Path:
    validate_fixture_bundle(payloads)
    required = set(FILE_KEYS.values())
    missing = required - set(payloads)
    if missing:
        raise ValueError(f"Fixture bundle is missing required files: {sorted(missing)}")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Write members with a fixed ZIP timestamp so deterministic fixture generation is byte-reproducible.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename in sorted(required):
            info = zipfile.ZipInfo(filename=filename, date_time=(2026, 8, 8, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = json.dumps(payloads[filename], indent=2, default=str, sort_keys=True).encode("utf-8")
            zf.writestr(info, data)
    return output

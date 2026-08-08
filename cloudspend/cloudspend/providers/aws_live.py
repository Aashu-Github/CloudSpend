from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound

from cloudspend.config import Settings
from cloudspend.ingestion.normalize import normalize_bundle
from cloudspend.providers.base import BaseProvider, ProviderResult


class AwsProvider(BaseProvider):
    """Read-only AWS adapter. It intentionally exposes no mutating AWS operations."""

    def __init__(
        self,
        profile_name: str | None = None,
        regions: list[str] | None = None,
        settings: Settings | None = None,
        session: boto3.Session | None = None,
    ):
        self.settings = settings or Settings.from_env()
        self.profile_name = profile_name or self.settings.aws_profile or None
        self.regions = regions or self.settings.regions()
        self._session = session

    def _session_or_create(self) -> boto3.Session:
        if self._session is not None:
            return self._session
        kwargs: dict[str, Any] = {}
        if self.profile_name:
            kwargs["profile_name"] = self.profile_name
        return boto3.Session(**kwargs)

    def load(self) -> ProviderResult:
        warnings: list[str] = []
        errors: list[str] = []
        try:
            session = self._session_or_create()
        except ProfileNotFound as exc:
            raise ValueError(f"AWS profile was not found: {self.profile_name}") from exc

        account_id = None
        arn = None
        try:
            identity = session.client("sts").get_caller_identity()
            account_id = identity.get("Account")
            arn = identity.get("Arn")
        except (ClientError, BotoCoreError) as exc:
            warnings.append(f"STS identity check unavailable: {type(exc).__name__}")

        all_resources = []
        scan_start = datetime.now(timezone.utc) - timedelta(days=self.settings.default_observation_days)
        scan_end = datetime.now(timezone.utc)
        account_cost_summary, summary_warnings = self._load_cost_summary(session, scan_start.date(), scan_end.date())
        warnings.extend(summary_warnings)

        for region in self.regions:
            try:
                ec2 = session.client("ec2", region_name=region)
                instances: list[dict[str, Any]] = []
                for page in ec2.get_paginator("describe_instances").paginate():
                    for reservation in page.get("Reservations", []):
                        instances.extend(reservation.get("Instances", []))
                volumes: list[dict[str, Any]] = []
                for page in ec2.get_paginator("describe_volumes").paginate():
                    volumes.extend(page.get("Volumes", []))

                metric_payload, metric_map, metric_warnings = self._load_metrics(session, region, instances, scan_start, scan_end)
                warnings.extend(metric_warnings)
                cost_payload, cost_warnings = self._load_resource_cost(session, instances, scan_start.date(), scan_end.date())
                warnings.extend(cost_warnings)

                payloads = {
                    "manifest.json": {
                        "bundle_version": "live-1.0",
                        "generated_at": scan_end.isoformat(),
                        "account_id": account_id,
                        "regions": [region],
                        "window_start": scan_start.isoformat(),
                        "window_end": scan_end.isoformat(),
                        "metric_queries": metric_map,
                    },
                    "ec2_describe_instances.json": {"Reservations": [{"Instances": instances}]},
                    "ec2_describe_volumes.json": {"Volumes": volumes},
                    "cloudwatch_get_metric_data.json": metric_payload,
                    "cost_explorer_get_cost_and_usage_with_resources.json": cost_payload,
                }
                all_resources.extend(normalize_bundle(payloads, mode="live", source_name=f"aws:{region}"))
            except (ClientError, BotoCoreError) as exc:
                errors.append(f"Region {region} failed: {type(exc).__name__}")
                continue

        if not all_resources and errors:
            raise ValueError("Live AWS scan did not return resources. " + " ".join(errors))
        return ProviderResult(
            resources=all_resources,
            warnings=warnings,
            errors=errors,
            source_info={
                "mode": "live",
                "profile": self.profile_name,
                "regions": self.regions,
                "account_id": account_id,
                "arn": arn,
                "account_cost_summary": account_cost_summary,
            },
        )

    def _load_metrics(
        self,
        session: boto3.Session,
        region: str,
        instances: list[dict[str, Any]],
        start: datetime,
        end: datetime,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        cloudwatch = session.client("cloudwatch", region_name=region)
        queries: list[dict[str, Any]] = []
        query_map: dict[str, Any] = {}
        period = 3600
        metric_defs = [
            ("CPUUtilization", "Percent"),
            ("NetworkIn", "Bytes"),
            ("NetworkOut", "Bytes"),
        ]
        for idx, instance in enumerate(instances):
            rid = instance.get("InstanceId")
            if not rid:
                continue
            for short, (metric_name, unit) in enumerate(metric_defs):
                qid = f"m{idx}_{short}"
                queries.append({
                    "Id": qid,
                    "MetricStat": {
                        "Metric": {"Namespace": "AWS/EC2", "MetricName": metric_name, "Dimensions": [{"Name": "InstanceId", "Value": rid}]},
                        "Period": period,
                        "Stat": "Average",
                    },
                    "ReturnData": True,
                })
                query_map[qid] = {"resource_id": rid, "metric_name": metric_name, "namespace": "AWS/EC2", "unit": unit}

        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        try:
            for offset in range(0, len(queries), 500):
                batch = queries[offset: offset + 500]
                if not batch:
                    continue
                token = None
                while True:
                    kwargs: dict[str, Any] = {"MetricDataQueries": batch, "StartTime": start, "EndTime": end, "ScanBy": "TimestampAscending"}
                    if token:
                        kwargs["NextToken"] = token
                    response = cloudwatch.get_metric_data(**kwargs)
                    results.extend(response.get("MetricDataResults", []))
                    token = response.get("NextToken")
                    if not token:
                        break
        except (ClientError, BotoCoreError) as exc:
            warnings.append(f"CloudWatch metrics unavailable in {region}: {type(exc).__name__}")
        return {"MetricDataResults": results}, query_map, warnings

    def _load_cost_summary(self, session: boto3.Session, start: date, end: date) -> tuple[dict[str, Any], list[str]]:
        """Best-effort account-level cost context; never used as per-resource billed cost."""
        warnings: list[str] = []
        try:
            ce = session.client("ce", region_name="us-east-1")
            response = ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": max(start + timedelta(days=1), end).isoformat()},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            # Keep only the compact cost result fields in persisted scan metadata.
            return {
                "ResultsByTime": response.get("ResultsByTime", []),
                "GroupDefinitions": response.get("GroupDefinitions", []),
            }, warnings
        except (ClientError, BotoCoreError) as exc:
            warnings.append(f"Account-level Cost Explorer summary unavailable: {type(exc).__name__}")
            return {"ResultsByTime": [], "GroupDefinitions": []}, warnings

    def _load_resource_cost(
        self,
        session: boto3.Session,
        instances: list[dict[str, Any]],
        start: date,
        end: date,
    ) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        if not instances:
            return {"ResultsByTime": [], "GroupDefinitions": []}, warnings
        try:
            ce = session.client("ce", region_name="us-east-1")
            results: list[dict[str, Any]] = []
            group_definitions: list[dict[str, Any]] = []
            token: str | None = None
            while True:
                kwargs: dict[str, Any] = {
                    "TimePeriod": {"Start": start.isoformat(), "End": max(start + timedelta(days=1), end).isoformat()},
                    "Granularity": "DAILY",
                    "Filter": {"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Elastic Compute Cloud - Compute"]}},
                    "Metrics": ["UnblendedCost"],
                    "GroupBy": [{"Type": "DIMENSION", "Key": "RESOURCE_ID"}],
                }
                if token:
                    kwargs["NextPageToken"] = token
                response = ce.get_cost_and_usage_with_resources(**kwargs)
                results.extend(response.get("ResultsByTime", []))
                group_definitions = response.get("GroupDefinitions", group_definitions)
                token = response.get("NextPageToken")
                if not token:
                    break
            return {"ResultsByTime": results, "GroupDefinitions": group_definitions}, warnings
        except (ClientError, BotoCoreError) as exc:
            warnings.append(
                "Resource-level Cost Explorer data is unavailable or not enabled; inventory and utilization analysis continued. "
                f"({type(exc).__name__})"
            )
            return {"ResultsByTime": [], "GroupDefinitions": []}, warnings

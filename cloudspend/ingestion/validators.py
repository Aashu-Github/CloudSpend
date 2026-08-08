from __future__ import annotations

import json
import mimetypes
import re
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from cloudspend.config import Settings

ALLOWED_EXTENSIONS = {".json", ".csv", ".xlsx", ".zip"}
DANGEROUS_EXTENSIONS = {".exe", ".dll", ".sh", ".bat", ".cmd", ".ps1", ".js", ".jar", ".xlsm"}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._ -]+$")


class UploadValidationError(ValueError):
    pass


def validate_upload_path(path: Path, settings: Settings) -> None:
    if not path.exists() or not path.is_file():
        raise UploadValidationError("Uploaded file does not exist.")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("Unsupported file type. Use JSON, CSV, XLSX, or ZIP.")
    if path.stat().st_size > settings.max_upload_bytes:
        raise UploadValidationError(f"File exceeds {settings.max_upload_mb} MB upload limit.")
    if path.suffix.lower() in DANGEROUS_EXTENSIONS:
        raise UploadValidationError("Executable or macro-enabled files are not supported.")
    validate_signature(path, settings)


def validate_original_filename(filename: str) -> None:
    if not filename or filename in {".", ".."}:
        raise UploadValidationError("Invalid filename.")
    if Path(filename).name != filename:
        raise UploadValidationError("Path components are not allowed in upload filenames.")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("Unsupported file type. Use JSON, CSV, XLSX, or ZIP.")
    if not _SAFE_NAME.fullmatch(filename):
        raise UploadValidationError("Filename contains unsupported characters.")


def validate_signature(path: Path, settings: Settings | None = None) -> None:
    suffix = path.suffix.lower()
    head = path.read_bytes()[:16]
    if suffix == ".zip" and not head.startswith(b"PK"):
        raise UploadValidationError("ZIP signature does not match file extension.")
    if suffix == ".xlsx":
        if not head.startswith(b"PK"):
            raise UploadValidationError("XLSX signature does not match file extension.")
        inspect_office_archive(path, settings or Settings.from_env())
    if suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise UploadValidationError("Malformed JSON upload.") from exc
    if suffix == ".csv" and b"\x00" in head:
        raise UploadValidationError("CSV appears to contain binary content.")


def inspect_office_archive(path: Path, settings: Settings) -> None:
    """Apply ZIP-bomb/path safety limits to XLSX containers without restricting Office member extensions."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            # XLSX legitimately contains more entries than a CloudSpend bundle, but still cap it.
            if len(infos) > max(500, settings.max_zip_files * 10):
                raise UploadValidationError("XLSX contains too many archive entries.")
            total = 0
            for info in infos:
                normalized = Path(info.filename.replace("\\", "/"))
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise UploadValidationError("XLSX contains path traversal entries.")
                if info.is_dir():
                    continue
                total += info.file_size
                if total > settings.max_zip_uncompressed_bytes:
                    raise UploadValidationError("XLSX expands beyond the configured size limit.")
                compressed = max(1, info.compress_size)
                if info.file_size > 1024 * 1024 and info.file_size / compressed > settings.max_zip_compression_ratio:
                    raise UploadValidationError("XLSX compression ratio is suspiciously high.")
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("Malformed XLSX upload.") from exc


def inspect_zip(path: Path, settings: Settings) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > settings.max_zip_files:
                raise UploadValidationError("ZIP contains too many files.")
            total = 0
            seen_basenames: set[str] = set()
            for info in infos:
                normalized = Path(info.filename.replace("\\", "/"))
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise UploadValidationError("ZIP contains path traversal entries.")
                if info.is_dir():
                    continue
                basename = Path(info.filename).name
                if basename in seen_basenames:
                    raise UploadValidationError("ZIP contains duplicate file basenames.")
                seen_basenames.add(basename)
                suffix = Path(info.filename).suffix.lower()
                if suffix not in ALLOWED_EXTENSIONS - {".zip"} and Path(info.filename).name != "manifest.json":
                    raise UploadValidationError(f"ZIP contains unsupported entry: {Path(info.filename).name}")
                total += info.file_size
                if total > settings.max_zip_uncompressed_bytes:
                    raise UploadValidationError("ZIP expands beyond the configured size limit.")
                compressed = max(1, info.compress_size)
                ratio = info.file_size / compressed
                if ratio > settings.max_zip_compression_ratio and info.file_size > 1024 * 1024:
                    raise UploadValidationError("ZIP compression ratio is suspiciously high.")
            return infos
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("Malformed ZIP upload.") from exc


def safe_mime_hint(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _parse_utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def validate_bundle_consistency(payloads: dict) -> list[str]:
    """Validate required source shapes and cross-file relationships before normalization/persistence."""
    errors: list[str] = []
    required_shapes = {
        "manifest.json": ("bundle_version",),
        "ec2_describe_instances.json": ("Reservations",),
        "ec2_describe_volumes.json": ("Volumes",),
        "cloudwatch_get_metric_data.json": ("MetricDataResults",),
        "cost_explorer_get_cost_and_usage_with_resources.json": ("ResultsByTime",),
    }
    for filename, required_keys in required_shapes.items():
        payload = payloads.get(filename)
        if not isinstance(payload, dict):
            errors.append(f"Missing or invalid required payload: {filename}.")
            continue
        for key in required_keys:
            if key not in payload:
                errors.append(f"{filename} is missing required top-level field {key}.")

    manifest = payloads.get("manifest.json") or {}
    window_start = _parse_utc(manifest.get("window_start"))
    window_end = _parse_utc(manifest.get("window_end"))
    if window_start and window_end and window_end < window_start:
        errors.append("Manifest observation window is reversed.")

    instances = {
        i.get("InstanceId")
        for r in (payloads.get("ec2_describe_instances.json") or {}).get("Reservations", [])
        for i in r.get("Instances", [])
        if i.get("InstanceId")
    }
    metric_map = manifest.get("metric_queries", {})
    metric_results = (payloads.get("cloudwatch_get_metric_data.json") or {}).get("MetricDataResults", [])
    for result in metric_results:
        query_id = result.get("Id")
        mapping = metric_map.get(query_id, {}) if query_id else {}
        if query_id and query_id not in metric_map:
            errors.append(f"Metric query {query_id} has no manifest resource mapping.")
        rid = mapping.get("resource_id") if isinstance(mapping, dict) else None
        if rid and rid not in instances:
            errors.append(f"Metric query {query_id} references unknown instance {rid}.")
        for raw_ts in result.get("Timestamps", []):
            ts = _parse_utc(raw_ts)
            if ts is None:
                errors.append(f"Metric query {query_id or '<unknown>'} contains an invalid timestamp.")
                continue
            if window_start and ts < window_start - timedelta(minutes=1):
                errors.append(f"Metric query {query_id or '<unknown>'} has a timestamp before the manifest window.")
            if window_end and ts > window_end + timedelta(minutes=1):
                errors.append(f"Metric query {query_id or '<unknown>'} has a timestamp after the manifest window.")

    for volume in (payloads.get("ec2_describe_volumes.json") or {}).get("Volumes", []):
        for attachment in volume.get("Attachments", []):
            rid = attachment.get("InstanceId")
            if rid and rid not in instances:
                errors.append(f"Volume {volume.get('VolumeId')} references unknown instance {rid}.")

    for period in (payloads.get("cost_explorer_get_cost_and_usage_with_resources.json") or {}).get("ResultsByTime", []):
        period_start = _parse_utc((period.get("TimePeriod") or {}).get("Start"))
        if period_start and window_start and period_start.date() < window_start.date():
            errors.append("Cost data contains a date before the manifest window.")
        if period_start and window_end and period_start.date() > window_end.date():
            errors.append("Cost data contains a date after the manifest window.")
        for group in period.get("Groups", []):
            found_resource_id = False
            for key in group.get("Keys", []):
                rid_match = re.search(r"i-[0-9a-fA-F]{8,17}", str(key))
                if rid_match:
                    found_resource_id = True
                    if rid_match.group(0) not in instances:
                        errors.append(f"Cost data references unknown instance {rid_match.group(0)}.")
            if group.get("Keys") and not found_resource_id:
                errors.append("Resource-level cost group does not contain a recognizable EC2 resource ID.")
            for metric in (group.get("Metrics") or {}).values():
                try:
                    if Decimal(str(metric.get("Amount", "0"))) < 0:
                        errors.append("Cost data contains a negative monetary value.")
                except Exception:
                    errors.append("Cost data contains an invalid monetary value.")
    return sorted(set(errors))

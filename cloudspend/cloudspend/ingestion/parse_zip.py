from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from cloudspend.config import Settings
from cloudspend.ingestion.validators import UploadValidationError, inspect_zip

EXPECTED_BUNDLE_FILES = {
    "manifest.json",
    "ec2_describe_instances.json",
    "ec2_describe_volumes.json",
    "cloudwatch_get_metric_data.json",
    "cost_explorer_get_cost_and_usage_with_resources.json",
}


def parse_bundle_zip(path: Path, settings: Settings) -> dict[str, Any]:
    infos = inspect_zip(path, settings)
    names = {Path(i.filename).name for i in infos if not i.is_dir()}
    if "manifest.json" not in names:
        raise UploadValidationError("ZIP is not a CloudSpend bundle: manifest.json is missing.")
    payloads: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="cloudspend_zip_") as temp:
        temp_root = Path(temp).resolve()
        with zipfile.ZipFile(path) as zf:
            for info in infos:
                if info.is_dir():
                    continue
                dest = (temp_root / Path(info.filename).name).resolve()
                if temp_root not in dest.parents:
                    raise UploadValidationError("Unsafe ZIP destination.")
                with zf.open(info) as source, dest.open("wb") as target:
                    target.write(source.read())
                if dest.suffix.lower() == ".json":
                    try:
                        payloads[dest.name] = json.loads(dest.read_text(encoding="utf-8"))
                    except Exception as exc:
                        raise UploadValidationError(f"Malformed JSON inside ZIP: {dest.name}") from exc
    manifest = payloads.get("manifest.json")
    if not isinstance(manifest, dict) or "bundle_version" not in manifest:
        raise UploadValidationError("CloudSpend manifest is invalid.")
    return payloads

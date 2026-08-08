from __future__ import annotations

from pathlib import Path

from cloudspend.config import Settings
from cloudspend.ingestion.detect import detect_json_family, detect_tabular_family
from cloudspend.ingestion.normalize import normalize_bundle, normalize_standalone_json, normalize_tabular
from cloudspend.ingestion.parse_csv import parse_csv
from cloudspend.ingestion.parse_json import parse_json
from cloudspend.ingestion.parse_xlsx import parse_xlsx
from cloudspend.ingestion.parse_zip import parse_bundle_zip
from cloudspend.ingestion.validators import UploadValidationError, validate_bundle_consistency, validate_upload_path
from cloudspend.providers.base import BaseProvider, ProviderResult


class FileProvider(BaseProvider):
    def __init__(self, path: str | Path, settings: Settings | None = None, display_name: str | None = None):
        self.path = Path(path)
        self.settings = settings or Settings.from_env()
        self.display_name = display_name or self.path.name

    def load(self) -> ProviderResult:
        validate_upload_path(self.path, self.settings)
        suffix = self.path.suffix.lower()
        warnings: list[str] = []
        source_info = {"mode": "file", "source_name": self.display_name}
        if suffix == ".zip":
            payloads = parse_bundle_zip(self.path, self.settings)
            consistency_errors = validate_bundle_consistency(payloads)
            if consistency_errors:
                raise UploadValidationError("Bundle consistency validation failed: " + " ".join(consistency_errors))
            resources = normalize_bundle(payloads, mode="file", source_name=self.display_name)
            source_info["family"] = "cloudspend_bundle"
        elif suffix == ".json":
            payload = parse_json(self.path)
            family = detect_json_family(payload)
            if family in {"unknown", "manifest"}:
                raise UploadValidationError("JSON schema is not recognized by deterministic import.")
            resources = normalize_standalone_json(payload, family, source_name=self.display_name)
            source_info["family"] = family
            if family in {"cloudwatch_get_metric_data", "cost_explorer"} and not resources:
                warnings.append("Metrics/cost-only JSON could not be correlated without inventory. Import a complete bundle for full analysis.")
        elif suffix == ".csv":
            df = parse_csv(self.path)
            family = detect_tabular_family([str(c) for c in df.columns])
            if family == "unknown":
                raise UploadValidationError("CSV columns are not recognized by deterministic import.")
            resources = normalize_tabular(df, self.display_name, family)
            source_info["family"] = family
        elif suffix == ".xlsx":
            df = parse_xlsx(self.path)
            family = detect_tabular_family([str(c) for c in df.columns])
            if family == "unknown":
                raise UploadValidationError("XLSX columns are not recognized by deterministic import.")
            resources = normalize_tabular(df, self.display_name, family)
            source_info["family"] = family
        else:
            raise UploadValidationError("Unsupported input format.")
        if not resources:
            warnings.append("No canonical resources were produced from this input.")
        return ProviderResult(resources=resources, warnings=warnings, source_info=source_info)

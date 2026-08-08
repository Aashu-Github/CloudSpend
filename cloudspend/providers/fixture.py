from __future__ import annotations

from pathlib import Path

from cloudspend.config import Settings
from cloudspend.ingestion.normalize import normalize_bundle
from cloudspend.ingestion.parse_zip import parse_bundle_zip
from cloudspend.ingestion.validators import validate_bundle_consistency, validate_upload_path
from cloudspend.providers.base import BaseProvider, ProviderResult


class FixtureProvider(BaseProvider):
    def __init__(self, path: str | Path, settings: Settings | None = None):
        self.path = Path(path)
        self.settings = settings or Settings.from_env()

    def load(self) -> ProviderResult:
        validate_upload_path(self.path, self.settings)
        payloads = parse_bundle_zip(self.path, self.settings)
        consistency_errors = validate_bundle_consistency(payloads)
        if consistency_errors:
            raise ValueError("Invalid fixture bundle: " + " ".join(consistency_errors))
        resources = normalize_bundle(payloads, mode="demo", source_name=self.path.name)
        return ProviderResult(
            resources=resources,
            source_info={
                "mode": "demo",
                "bundle_version": (payloads.get("manifest.json") or {}).get("bundle_version"),
                "manifest": payloads.get("manifest.json", {}),
            },
        )

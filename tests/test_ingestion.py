from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from cloudspend.ai.fixture_generator import generate_deterministic_bundle, write_bundle_zip
from cloudspend.config import Settings
from cloudspend.ingestion.normalize import normalize_tabular
from cloudspend.ingestion.validators import UploadValidationError, inspect_zip, validate_original_filename
from cloudspend.providers.file_upload import FileProvider


def test_zip_provider_and_standalone_aws_json(tmp_path: Path):
    bundle = generate_deterministic_bundle(instance_count=6, seed=9)
    zip_path = write_bundle_zip(bundle, tmp_path / "bundle.zip")
    result = FileProvider(zip_path, Settings()).load()
    assert len(result.resources) >= 8

    ec2_path = tmp_path / "instances.json"
    ec2_path.write_text(json.dumps(bundle["ec2_describe_instances.json"]), encoding="utf-8")
    partial = FileProvider(ec2_path, Settings()).load()
    assert len(partial.resources) == 6
    assert all(r.resource_type == "ec2_instance" for r in partial.resources)


def test_canonical_csv_preserves_unknown_fields(tmp_path: Path):
    path = tmp_path / "canonical.csv"
    pd.DataFrame([
        {
            "resource_id": "i-0123456789abcdef0",
            "resource_type": "ec2_instance",
            "region": "us-east-1",
            "state": "running",
            "instance_type": "t3.large",
            "cpu_avg": 3.0,
            "cpu_p95": 7.0,
            "owner_team": "payments",
        }
    ]).to_csv(path, index=False)
    result = FileProvider(path, Settings()).load()
    assert result.resources[0].source_metadata["owner_team"] == "payments"


def test_cur_like_cost_is_allocated_not_actual():
    df = pd.DataFrame([
        {"line_item_resource_id": "i-0123456789abcdef0", "line_item_unblended_cost": "3.50", "product_region": "us-east-1", "line_item_product_code": "AmazonEC2"},
        {"line_item_resource_id": "i-0123456789abcdef0", "line_item_unblended_cost": "4.25", "product_region": "us-east-1", "line_item_product_code": "AmazonEC2"},
    ])
    resource = normalize_tabular(df, "cur.csv", "cur_like")[0]
    assert resource.costs.actual_resource_cost is None
    assert str(resource.costs.allocated_cost) == "7.75"


def test_upload_filename_and_zip_traversal_are_rejected(tmp_path: Path):
    with pytest.raises(UploadValidationError):
        validate_original_filename("../evil.json")
    with pytest.raises(UploadValidationError):
        validate_original_filename("macro.xlsm")

    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", '{"bundle_version":"1.0"}')
        zf.writestr("../escape.json", "{}")
    with pytest.raises(UploadValidationError):
        inspect_zip(zip_path, Settings())


def test_canonical_json_preserves_unknown_top_level_fields(tmp_path: Path):
    payload = {
        "provider": "aws",
        "region": "us-east-1",
        "resource_type": "ec2_instance",
        "resource_id": "i-0123456789abcdef0",
        "state": "running",
        "source_lineage": {"provider_mode": "file", "source_name": "custom.json"},
        "ec2": {"instance_type": "t3.large"},
        "custom_owner_field": "platform-team",
    }
    path = tmp_path / "canonical.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = FileProvider(path, Settings()).load()
    assert result.resources[0].source_metadata["custom_owner_field"] == "platform-team"

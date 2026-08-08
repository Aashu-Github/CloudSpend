from __future__ import annotations

from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

from cloudspend.web import create_app  # noqa: E402


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'public-api.db'}")
    monkeypatch.setenv("CORS_ORIGINS", "https://aashu-github.github.io,http://127.0.0.1:8000")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_public_demo_returns_scan_payload_and_cors(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    origin = "https://aashu-github.github.io"
    response = client.post("/api/public/demo", headers={"Origin": origin, "Accept": "application/json"})
    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") == origin
    scan_id = response.get_json()["scan_id"]

    scan = client.get(f"/api/public/scans/{scan_id}", headers={"Origin": origin})
    assert scan.status_code == 200
    data = scan.get_json()
    assert data["source_mode"] == "demo"
    assert data["resources"]
    assert data["summary"]["resource_count"] == len(data["resources"])
    assert "chart" in data


def test_public_import_uses_same_secure_ingestion_pipeline(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    sample = Path(__file__).resolve().parents[1] / "samples" / "ec2_describe_instances.json"
    with sample.open("rb") as handle:
        response = client.post(
            "/api/public/import",
            data={"file": (handle, sample.name)},
            content_type="multipart/form-data",
            headers={"Origin": "https://aashu-github.github.io", "Accept": "application/json"},
        )
    assert response.status_code == 200
    assert response.get_json()["scan_id"]


def test_public_api_does_not_reflect_unapproved_origins(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.get("/api/public/health", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") is None

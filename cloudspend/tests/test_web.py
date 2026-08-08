from __future__ import annotations

import pytest

flask = pytest.importorskip("flask")

from cloudspend.web import create_app  # noqa: E402


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'web.db'}")
    app = create_app()
    app.config.update(TESTING=True)
    return app, app.test_client()


def _csrf(client) -> str:
    client.get("/")
    with client.session_transaction() as session:
        return session["csrf_token"]


def test_home_and_security_headers(monkeypatch, tmp_path):
    _, client = _client(monkeypatch, tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert b"Cloud" in response.data and b"Optimizer" in response.data
    assert b"Inside the project" in response.data
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_import_page_uses_native_file_input_and_external_initializer(monkeypatch, tmp_path):
    _, client = _client(monkeypatch, tmp_path)
    response = client.get("/import")
    assert response.status_code == 200
    assert b'id="drop-zone"' in response.data
    assert b'for="file-input"' in response.data
    assert b'id="file-input"' in response.data
    assert b"CloudSpend.initImport()" not in response.data


def test_live_aws_fetch_failure_stays_json(monkeypatch, tmp_path):
    _, client = _client(monkeypatch, tmp_path)
    token = _csrf(client)

    def fail_load(_self):
        raise ValueError("profile missing")

    monkeypatch.setattr("cloudspend.web.routes.AwsProvider.load", fail_load)
    response = client.post(
        "/api/aws/scan",
        data={"csrf_token": token, "profile": "missing-profile", "regions": "us-east-1"},
        headers={"Accept": "application/json", "X-Requested-With": "fetch"},
    )
    assert response.status_code == 400
    assert response.is_json
    assert "could not connect to AWS" in response.get_json()["error"]
    assert response.headers.get("Location") is None

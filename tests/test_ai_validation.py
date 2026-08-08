from __future__ import annotations

import pytest

from cloudspend.ai.fixture_generator import generate_ai_bundle


class BadProvider:
    name = "bad"
    def generate_json(self, _system: str, _user: str):
        return {"manifest": {"bundle_version": "1.0"}}


def test_ai_fixture_requires_all_payloads():
    with pytest.raises(ValueError):
        generate_ai_bundle(BadProvider(), "test", 4, 2, ["us-east-1"], 14, 42)

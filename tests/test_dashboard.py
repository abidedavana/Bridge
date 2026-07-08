"""Dashboard API: serves the run-state JSON and the single page.

Skipped cleanly if the optional [dashboard] extras aren't installed, so the core
test suite still runs without FastAPI.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from bridge.dashboard.app import create_app  # noqa: E402
from bridge.run_state import RunRecorder, RunState  # noqa: E402


def test_api_reports_no_run_before_any_run(tmp_path):
    client = TestClient(create_app(str(tmp_path / "current.json")))
    r = client.get("/api/state")
    assert r.status_code == 200
    assert r.json()["status"] == "NO_RUN"


def test_api_returns_recorded_state(tmp_path):
    p = tmp_path / "current.json"
    RunRecorder(str(p), RunState(run_id="r1", scenario="success", executor="mock", llm_model="llama"))
    client = TestClient(create_app(str(p)))
    body = client.get("/api/state").json()
    assert body["run_id"] == "r1"
    assert body["scenario"] == "success"
    assert body["llm_model"] == "llama"


def test_index_page_is_served(tmp_path):
    client = TestClient(create_app(str(tmp_path / "current.json")))
    r = client.get("/")
    assert r.status_code == 200
    assert "Bridge" in r.text and "/api/state" in r.text

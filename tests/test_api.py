"""REST integration tests, skipped when optional API dependencies are absent."""

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from cohortseal.api import create_app
from cohortseal.config import Settings


def test_api_health_audit_and_retrieval(tmp_path, cases):
    """Primary API path validates, persists, and returns an audit run."""
    app = create_app(Settings(database_url=str(tmp_path / "api.db")))
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    response = client.post("/v1/audits", json={"dataset_name": "synthetic", "cases": [c.model_dump() for c in cases]})
    assert response.status_code == 201
    run_id = response.json()["run_id"]
    assert client.get(f"/v1/audits/{run_id}").status_code == 200
    assert client.get("/v1/audits?limit=0").status_code == 422

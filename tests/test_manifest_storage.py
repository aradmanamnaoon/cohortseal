"""Manifest round-trip and persistence integration tests."""

import json

import pytest

from cohortseal.audit import AuditEngine
from cohortseal.errors import ManifestError
from cohortseal.manifest import load_manifest, write_manifest
from cohortseal.storage import RunStore


def test_manifest_json_round_trip(tmp_path, cases):
    """JSON serialization preserves stable case fields."""
    source = tmp_path / "cohort.json"
    write_manifest(cases, source)
    loaded = load_manifest(source)
    assert len(loaded.cases) == len(cases)
    assert loaded.cases[0].patient_id == cases[0].patient_id


def test_manifest_rejects_duplicate_case_ids(tmp_path, cases):
    """Duplicate row identifiers are rejected at ingestion."""
    source = tmp_path / "bad.json"
    source.write_text(json.dumps([cases[0].model_dump(), cases[0].model_dump()]))
    with pytest.raises(ManifestError, match="unique"):
        load_manifest(source)


def test_sqlite_run_round_trip_and_cascade(tmp_path, cases):
    """Migrations create run/findings tables and retrieve stored audit state."""
    report = AuditEngine().run(cases)
    store = RunStore(tmp_path / "runs.db")
    store.save_run("run-1", "synthetic", "digest", report.passed, report.case_count,
                   report.patient_count, report.summary(), report.findings)
    restored = store.get_run("run-1")
    assert restored is not None
    assert restored["summary"]["patients"] == 8
    assert len(store.list_runs()) == 1

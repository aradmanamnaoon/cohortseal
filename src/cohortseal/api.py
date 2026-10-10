"""Optional FastAPI interface for manifest audits and stored run retrieval."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from pydantic import BaseModel, Field

from cohortseal.audit import AuditEngine
from cohortseal.cohort_drift import CohortDriftMonitor
from cohortseal.config import Settings
from cohortseal.errors import CohortSealError
from cohortseal.models import CaseRecord
from cohortseal.plugins import RuleRegistry
from cohortseal.profile import CohortProfiler
from cohortseal.provenance import validate_pipeline_dict
from cohortseal.splitting import make_group_split
from cohortseal.storage import RunStore


class AuditRequest(BaseModel):
    """Request body for an in-memory manifest audit."""

    dataset_name: str = Field(min_length=1, max_length=200)
    cases: list[CaseRecord] = Field(min_length=1, max_length=1_000_000)


class CohortRequest(BaseModel):
    """Request body for profile or split operations."""

    cases: list[CaseRecord] = Field(min_length=1, max_length=1_000_000)
    seed: int = 42
    fractions: dict[str, float] | None = None
    stratify_by: tuple[str, ...] = ("label",)
    holdout_site: str | None = None


class DriftRequest(BaseModel):
    """Request body for aggregate reference/current cohort comparison."""

    reference: list[CaseRecord] = Field(min_length=1, max_length=1_000_000)
    current: list[CaseRecord] = Field(min_length=1, max_length=1_000_000)


class PipelineRequest(BaseModel):
    """Request body for a declarative preprocessing audit."""

    steps: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)


def create_app(settings: Settings | None = None) -> Any:
    """Create the HTTP application; importing this function does not require FastAPI."""
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:
        raise RuntimeError("install cohortseal[api] to use the REST API") from exc
    config = settings or Settings()
    store = RunStore(config.database_url)
    registry = RuleRegistry()
    registry.discover()
    engine = AuditEngine(registry.all())
    app = FastAPI(title="CohortSeal API", version="0.1.0", description="Cohort integrity checks for medical imaging ML.")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness endpoint with no patient data."""
        return {"status": "ok", "service": "cohortseal"}

    @app.post("/v1/audits", status_code=201)
    def audit(request: AuditRequest) -> dict[str, Any]:
        """Audit supplied case metadata and persist result."""
        ids = [case.case_id for case in request.cases]
        if len(ids) != len(set(ids)):
            raise HTTPException(status_code=422, detail="case_id values must be unique")
        report = engine.run(request.cases)
        run_id = str(uuid.uuid4())
        encoded = json.dumps([case.model_dump(mode="json") for case in request.cases], sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        try:
            store.save_run(run_id, request.dataset_name, digest, report.passed,
                           report.case_count, report.patient_count, report.summary(), report.findings)
        except CohortSealError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"run_id": run_id, **report.summary(),
                "findings": [item.model_dump(mode="json") for item in report.findings]}

    @app.get("/v1/audits")
    def list_audits(limit: int = 50) -> list[dict[str, Any]]:
        """List summary metadata for recent audit runs."""
        if not 1 <= limit <= 1000:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 1000")
        return store.list_runs(limit)

    @app.get("/v1/audits/{run_id}")
    def get_audit(run_id: str) -> dict[str, Any]:
        """Fetch a run and its findings by UUID."""
        result = store.get_run(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="audit run not found")
        return result

    @app.post("/v1/cohort-profile")
    def cohort_profile(request: AuditRequest) -> dict[str, Any]:
        """Return site, label, modality, and split coverage counts."""
        return CohortProfiler().profile(request.cases).to_dict()

    @app.post("/v1/splits")
    def create_split(request: CohortRequest) -> dict[str, Any]:
        """Create reproducible patient-group assignments without reading image files."""
        try:
            plan = make_group_split(request.cases, request.fractions, seed=request.seed,
                                    stratify_by=request.stratify_by, holdout_site=request.holdout_site)
        except (ValueError, CohortSealError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"digest": plan.digest, "seed": plan.seed,
                "assignments": [item.model_dump(mode="json") for item in plan.assignments],
                "fractions": dict(plan.fractions)}

    @app.post("/v1/pipelines/audit")
    def pipeline_audit(request: PipelineRequest) -> dict[str, Any]:
        """Check declared preprocessing fit scopes and operation ordering."""
        try:
            result = validate_pipeline_dict(request.steps)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.to_dict()

    @app.post("/v1/cohorts/drift")
    def cohort_drift(request: DriftRequest) -> dict[str, Any]:
        """Compare aggregate metadata distributions between two cohort manifests."""
        try:
            shifts = CohortDriftMonitor().compare(request.reference, request.current)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return CohortDriftMonitor.summary(shifts)

    return app

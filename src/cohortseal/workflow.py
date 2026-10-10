"""Composable high-level cohort workflow shared by CLI and API adapters."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Iterable

from cohortseal.audit import AuditEngine, AuditReport
from cohortseal.lineage import LineageGraph, LineageReport
from cohortseal.models import CaseRecord, Finding, Severity
from cohortseal.profile import CohortProfiler, SplitProfile
from cohortseal.provenance import PipelineAuditor, PipelineStep, ProvenanceReport
from cohortseal.reporting import ReportBuilder, ReportArtifact
from cohortseal.storage import RunStore


logger = logging.getLogger("cohortseal.workflow")


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """All validation products generated from one immutable manifest snapshot."""

    dataset_name: str
    manifest_digest: str
    audit: AuditReport
    profile: SplitProfile
    lineage: LineageReport
    provenance: ProvenanceReport | None
    findings: tuple[Finding, ...]
    run_id: str | None
    report_artifact: ReportArtifact | None = None

    @property
    def passed(self) -> bool:
        """Return whether all included checks passed at error severity."""
        return not any(item.severity == Severity.ERROR for item in self.findings)

    def summary(self) -> dict[str, object]:
        """Build an aggregate summary that omits patient identifiers."""
        return {
            "dataset_name": self.dataset_name,
            "manifest_digest": self.manifest_digest,
            "passed": self.passed,
            "run_id": self.run_id,
            "cases": self.profile.total_cases,
            "patients": self.profile.total_patients,
            "finding_count": len(self.findings),
            "error_count": sum(item.severity == Severity.ERROR for item in self.findings),
            "warning_count": sum(item.severity == Severity.WARNING for item in self.findings),
            "profile": self.profile.to_dict(),
        }


class CohortWorkflow:
    """Run independent checks and optionally store a report for one cohort."""

    def __init__(self, *, audit_engine: AuditEngine | None = None,
                 profiler: CohortProfiler | None = None,
                 store: RunStore | None = None) -> None:
        self.audit_engine = audit_engine or AuditEngine()
        self.profiler = profiler or CohortProfiler()
        self.store = store

    def run(self, dataset_name: str, cases: Iterable[CaseRecord], *,
            pipeline_steps: Iterable[PipelineStep] | None = None,
            report_path: str | None = None) -> WorkflowResult:
        """Audit, profile, verify lineage/provenance, persist, and render one run."""
        snapshot = tuple(cases)
        if not dataset_name.strip():
            raise ValueError("dataset_name must not be blank")
        if not snapshot:
            raise ValueError("cases must not be empty")
        encoded = json.dumps([item.model_dump(mode="json") for item in snapshot],
                             sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        audit = self.audit_engine.run(snapshot)
        profile = self.profiler.profile(snapshot)
        lineage = LineageGraph().audit(snapshot)
        provenance = PipelineAuditor().audit(pipeline_steps) if pipeline_steps is not None else None
        combined = list(audit.findings) + list(profile.findings) + list(lineage.findings)
        if provenance:
            combined.extend(provenance.findings)
        findings = tuple(combined)
        run_id: str | None = None
        if self.store:
            import uuid
            run_id = str(uuid.uuid4())
            self.store.save_run(run_id, dataset_name, digest, not any(
                item.severity == Severity.ERROR for item in findings), len(snapshot),
                len({item.patient_id for item in snapshot}),
                {"finding_count": len(findings), "error_count": sum(
                    item.severity == Severity.ERROR for item in findings)}, findings)
        artifact = None
        if report_path:
            builder = ReportBuilder(title=f"CohortSeal: {dataset_name}")
            payload = builder.build_payload(audit, profile, dataset_name=dataset_name,
                                            manifest_digest=digest)
            payload["lineage"] = lineage.to_dict()
            payload["provenance"] = provenance.to_dict() if provenance else None
            payload["overall_passed"] = not any(item.severity == Severity.ERROR for item in findings)
            payload["all_findings"] = [item.model_dump(mode="json") for item in findings]
            suffix = report_path.lower().rsplit(".", 1)[-1] if "." in report_path else "md"
            if suffix == "html":
                content, format_name = builder.render_html(payload), "html"
            elif suffix == "json":
                content, format_name = builder.render_json(payload), "json"
            else:
                content, format_name = builder.render_markdown(payload), "markdown"
            artifact = builder.write(content, report_path,
                                     format_name=format_name)
        logger.info("cohort workflow complete", extra={
            "dataset_name": dataset_name, "run_id": run_id,
            "case_count": len(snapshot), "patient_count": len({item.patient_id for item in snapshot}),
            "finding_count": len(findings), "passed": not any(
                item.severity == Severity.ERROR for item in findings),
        })
        return WorkflowResult(dataset_name, digest, audit, profile, lineage,
                              provenance, findings, run_id, artifact)

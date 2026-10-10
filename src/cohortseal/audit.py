"""Dataset and split integrity checks designed for medical image cohorts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Protocol

from cohortseal.models import CaseRecord, Finding, Severity


class AuditRule(Protocol):
    """Extension contract for dataset integrity checks."""

    @property
    def code(self) -> str:
        """Return a stable rule code suitable for CI allowlists."""

    def run(self, cases: tuple[CaseRecord, ...]) -> Iterable[Finding]:
        """Yield findings for a dataset snapshot."""


@dataclass(frozen=True, slots=True)
class AuditReport:
    """Audit result that can be serialized or stored as an immutable run."""

    findings: tuple[Finding, ...]
    case_count: int
    patient_count: int
    rule_count: int

    @property
    def passed(self) -> bool:
        """Whether the audit has no error-level findings."""
        return not any(item.severity == Severity.ERROR for item in self.findings)

    def summary(self) -> dict[str, int | bool]:
        """Return count-only summary without patient identifiers."""
        return {
            "passed": self.passed,
            "cases": self.case_count,
            "patients": self.patient_count,
            "findings": len(self.findings),
            "errors": sum(item.severity == Severity.ERROR for item in self.findings),
            "warnings": sum(item.severity == Severity.WARNING for item in self.findings),
        }


class PatientSplitRule:
    """Reject patient groups that occur in more than one declared split."""

    @property
    def code(self) -> str:
        """Stable audit code."""
        return "PATIENT_CROSS_SPLIT"

    def run(self, cases: tuple[CaseRecord, ...]) -> Iterable[Finding]:
        """Find patients represented in multiple splits."""
        patient_splits: dict[str, set[str]] = defaultdict(set)
        patient_cases: dict[str, list[str]] = defaultdict(list)
        for case in cases:
            if case.split:
                patient_splits[case.patient_id].add(case.split)
                patient_cases[case.patient_id].append(case.case_id)
        for patient, splits in sorted(patient_splits.items()):
            if len(splits) > 1:
                yield Finding(
                    code=self.code,
                    severity=Severity.ERROR,
                    message="Patient group appears in multiple splits.",
                    case_ids=tuple(sorted(patient_cases[patient])),
                    evidence={"split_count": len(splits)},
                )


class ExactDuplicateRule:
    """Flag identical content hashes assigned across different splits."""

    @property
    def code(self) -> str:
        """Stable audit code."""
        return "DUPLICATE_CONTENT_CROSS_SPLIT"

    def run(self, cases: tuple[CaseRecord, ...]) -> Iterable[Finding]:
        """Find repeated hashes that cross split boundaries."""
        groups: dict[str, list[CaseRecord]] = defaultdict(list)
        for case in cases:
            if case.content_sha256:
                groups[case.content_sha256.lower()].append(case)
        for digest, matches in sorted(groups.items()):
            splits = {case.split for case in matches if case.split}
            if len(splits) > 1:
                yield Finding(
                    code=self.code,
                    severity=Severity.ERROR,
                    message="Byte-identical content is present in multiple splits.",
                    case_ids=tuple(sorted(case.case_id for case in matches)),
                    evidence={"digest_prefix": digest[:12], "split_count": len(splits)},
                )


class MissingMetadataRule:
    """Report missing patient/site/label values needed for stated audits."""

    def __init__(self, required_fields: tuple[str, ...] = ("site",)) -> None:
        self.required_fields = required_fields

    @property
    def code(self) -> str:
        """Stable audit code."""
        return "MISSING_STRATIFICATION_METADATA"

    def run(self, cases: tuple[CaseRecord, ...]) -> Iterable[Finding]:
        """Report per-field missing counts, never rendering raw values."""
        for field in self.required_fields:
            missing = tuple(sorted(case.case_id for case in cases if not getattr(case, field, None)))
            if missing:
                yield Finding(
                    code=self.code,
                    severity=Severity.WARNING,
                    message=f"Required field '{field}' is missing for {len(missing)} cases.",
                    case_ids=missing,
                    evidence={"field": field, "missing_count": len(missing)},
                )


class AuditEngine:
    """Run built-in and user-supplied rules against case manifests."""

    def __init__(self, rules: Iterable[AuditRule] | None = None) -> None:
        self.rules = tuple(rules or (PatientSplitRule(), ExactDuplicateRule(), MissingMetadataRule()))
        codes = [rule.code for rule in self.rules]
        if len(codes) != len(set(codes)):
            raise ValueError("audit rule codes must be unique")

    def run(self, cases: Iterable[CaseRecord]) -> AuditReport:
        """Evaluate all registered rules and summarize the cohort."""
        snapshot = tuple(cases)
        findings = tuple(finding for rule in self.rules for finding in rule.run(snapshot))
        return AuditReport(
            findings=findings,
            case_count=len(snapshot),
            patient_count=len({case.patient_id for case in snapshot}),
            rule_count=len(self.rules),
        )

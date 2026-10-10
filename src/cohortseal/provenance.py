"""Preprocessing provenance contracts and leakage-order checks.

This module audits a declarative record of data-dependent preprocessing. It does not
attempt to infer arbitrary Python program behavior; callers must describe the pipeline
stages they execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from cohortseal.models import Finding, Severity


class PipelinePhase(str, Enum):
    """Ordered lifecycle phases for a medical imaging experiment."""

    INGEST = "ingest"
    SPLIT = "split"
    FIT = "fit"
    TRANSFORM = "transform"
    EVALUATE = "evaluate"

    @property
    def order(self) -> int:
        """Return canonical phase order."""
        return list(PipelinePhase).index(self)


class FitScope(str, Enum):
    """Sample population used to estimate preprocessing parameters."""

    FIXED = "fixed"
    PER_CASE = "per_case"
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    ALL = "all"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PipelineStep:
    """One documented operation in a preprocessing pipeline."""

    name: str
    phase: PipelinePhase
    data_dependent: bool = False
    fit_scope: FitScope = FitScope.FIXED
    fitted_before_split: bool = False
    applied_to: tuple[str, ...] = ()
    random: bool = False
    seed: int | None = None
    parameters: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject ambiguous names and invalid application scopes."""
        if not self.name.strip():
            raise ValueError("pipeline step name must not be blank")
        if len(set(self.applied_to)) != len(self.applied_to):
            raise ValueError("applied_to contains duplicate split names")


@dataclass(frozen=True, slots=True)
class ProvenanceReport:
    """Validated preprocessing declaration and reproducibility findings."""

    steps: tuple[PipelineStep, ...]
    findings: tuple[Finding, ...]

    @property
    def passed(self) -> bool:
        """Whether no error-level leakage finding exists."""
        return not any(item.severity == Severity.ERROR for item in self.findings)

    def to_dict(self) -> dict[str, object]:
        """Serialize the declared pipeline without arbitrary executable content."""
        return {
            "passed": self.passed,
            "steps": [
                {
                    "name": step.name,
                    "phase": step.phase.value,
                    "data_dependent": step.data_dependent,
                    "fit_scope": step.fit_scope.value,
                    "fitted_before_split": step.fitted_before_split,
                    "applied_to": list(step.applied_to),
                    "random": step.random,
                    "seed": step.seed,
                    "parameters": dict(step.parameters),
                }
                for step in self.steps
            ],
            "findings": [item.model_dump(mode="json") for item in self.findings],
        }


class PipelineAuditor:
    """Check fit-scope and phase declarations for common preprocessing leakage."""

    _VALID_SCOPES = {"train", "validation", "test"}

    def audit(self, steps: Iterable[PipelineStep]) -> ProvenanceReport:
        """Validate pipeline ordering, fitted populations, and random seeds."""
        ordered = tuple(steps)
        findings: list[Finding] = []
        previous_order = -1
        split_seen = False
        names: set[str] = set()
        for index, step in enumerate(ordered):
            if step.name in names:
                findings.append(self._finding("DUPLICATE_PIPELINE_STEP", Severity.ERROR,
                                              f"Pipeline step '{step.name}' is declared more than once.", index))
            names.add(step.name)
            if step.phase.order < previous_order:
                findings.append(self._finding("PIPELINE_PHASE_ORDER", Severity.ERROR,
                                              f"Pipeline phase '{step.phase.value}' occurs after a later phase.", index))
            previous_order = max(previous_order, step.phase.order)
            if step.phase == PipelinePhase.SPLIT:
                split_seen = True
            if step.data_dependent:
                if step.fitted_before_split or (not split_seen and step.phase != PipelinePhase.SPLIT):
                    findings.append(self._finding("FIT_BEFORE_SPLIT", Severity.ERROR,
                                                  f"Data-dependent step '{step.name}' is fitted before splitting.", index))
                if step.fit_scope in (FitScope.ALL, FitScope.VALIDATION, FitScope.TEST, FitScope.UNKNOWN):
                    findings.append(self._finding("NON_TRAIN_FIT_SCOPE", Severity.ERROR,
                                                  f"Data-dependent step '{step.name}' uses fit scope '{step.fit_scope.value}'.", index))
                if step.fit_scope not in (FitScope.TRAIN, FitScope.FIXED, FitScope.PER_CASE):
                    continue
                if step.fit_scope == FitScope.TRAIN and "train" not in step.applied_to:
                    findings.append(self._finding("TRAIN_FIT_NOT_APPLIED_TO_TRAIN", Severity.WARNING,
                                                  f"Step '{step.name}' is fitted on train but does not declare train application.", index))
            if step.random and step.seed is None:
                findings.append(self._finding("UNSEEDED_RANDOM_TRANSFORM", Severity.WARNING,
                                              f"Random step '{step.name}' does not declare a seed.", index))
            if step.phase == PipelinePhase.EVALUATE and step.applied_to and "test" not in step.applied_to:
                findings.append(self._finding("TEST_EVALUATION_SCOPE", Severity.WARNING,
                                              f"Evaluation step '{step.name}' does not declare test scope.", index))
            unknown = set(step.applied_to) - self._VALID_SCOPES
            if unknown:
                findings.append(self._finding("UNKNOWN_SPLIT_SCOPE", Severity.ERROR,
                                              f"Step '{step.name}' names unsupported split scopes: {sorted(unknown)}.", index))
        if not any(step.phase == PipelinePhase.SPLIT for step in ordered):
            findings.append(Finding(code="SPLIT_PHASE_MISSING", severity=Severity.WARNING,
                                    message="Pipeline declaration contains no explicit split phase."))
        return ProvenanceReport(steps=ordered, findings=tuple(findings))

    @staticmethod
    def _finding(code: str, severity: Severity, message: str, index: int) -> Finding:
        """Build a finding whose evidence points at the declared step index."""
        return Finding(code=code, severity=severity, message=message,
                       evidence={"step_index": index})


def validate_pipeline_dict(payload: Iterable[Mapping[str, object]]) -> ProvenanceReport:
    """Convert JSON-like step mappings to typed records and audit them."""
    steps: list[PipelineStep] = []
    for index, item in enumerate(payload):
        try:
            steps.append(PipelineStep(
                name=str(item["name"]),
                phase=PipelinePhase(str(item["phase"])),
                data_dependent=bool(item.get("data_dependent", False)),
                fit_scope=FitScope(str(item.get("fit_scope", "fixed"))),
                fitted_before_split=bool(item.get("fitted_before_split", False)),
                applied_to=tuple(str(value) for value in item.get("applied_to", ())),  # type: ignore[arg-type]
                random=bool(item.get("random", False)),
                seed=int(item["seed"]) if item.get("seed") is not None else None,
                parameters=item.get("parameters", {}),  # type: ignore[arg-type]
            ))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid pipeline step at index {index}: {exc}") from exc
    return PipelineAuditor().audit(steps)

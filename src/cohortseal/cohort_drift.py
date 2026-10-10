"""Metadata distribution shift checks between reference and incoming cohorts."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from cohortseal.models import CaseRecord, Finding, Severity


@dataclass(frozen=True, slots=True)
class DistributionShift:
    """Distribution comparison for one categorical metadata field."""

    field: str
    reference_count: int
    current_count: int
    categories: tuple[str, ...]
    reference_proportions: Mapping[str, float]
    current_proportions: Mapping[str, float]
    population_stability_index: float
    jensen_shannon_divergence: float
    findings: tuple[Finding, ...]

    def to_dict(self) -> dict[str, object]:
        """Serialize aggregate proportions and shift checks."""
        return {
            "field": self.field, "reference_count": self.reference_count,
            "current_count": self.current_count, "categories": list(self.categories),
            "reference_proportions": dict(self.reference_proportions),
            "current_proportions": dict(self.current_proportions),
            "population_stability_index": self.population_stability_index,
            "jensen_shannon_divergence": self.jensen_shannon_divergence,
            "findings": [item.model_dump(mode="json") for item in self.findings],
        }


def _normalize(counter: Counter[str], categories: tuple[str, ...], alpha: float) -> dict[str, float]:
    """Normalize smoothed categorical counts to proportions."""
    denominator = sum(counter.values()) + alpha * len(categories)
    if denominator == 0:
        return {category: 0.0 for category in categories}
    return {category: (counter.get(category, 0) + alpha) / denominator for category in categories}


def _psi(expected: Mapping[str, float], actual: Mapping[str, float]) -> float:
    """Compute smoothed population stability index over aligned categories."""
    epsilon = 1e-9
    return sum((actual[key] - expected[key]) * math.log(
        max(actual[key], epsilon) / max(expected[key], epsilon)) for key in expected)


def _jsd(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """Compute Jensen-Shannon divergence in natural-log units."""
    midpoint = {key: (left[key] + right[key]) / 2 for key in left}
    def kl(source: Mapping[str, float]) -> float:
        return sum(value * math.log(value / midpoint[key]) for key, value in source.items() if value > 0)
    return (kl(left) + kl(right)) / 2


class CohortDriftMonitor:
    """Compare categorical site, modality, label, or caller-selected cohort fields."""

    def __init__(self, *, fields: tuple[str, ...] = ("site", "modality", "label"),
                 psi_warning: float = 0.1, psi_error: float = 0.25,
                 smoothing: float = 0.5, minimum_records: int = 20) -> None:
        if not fields or set(fields) - {"site", "modality", "label"}:
            raise ValueError("fields must be a non-empty subset of site, modality, and label")
        if psi_warning < 0 or psi_error <= psi_warning:
            raise ValueError("psi_error must be greater than non-negative psi_warning")
        if smoothing < 0 or minimum_records < 1:
            raise ValueError("smoothing must be non-negative and minimum_records positive")
        self.fields = fields
        self.psi_warning = psi_warning
        self.psi_error = psi_error
        self.smoothing = smoothing
        self.minimum_records = minimum_records

    def compare(self, reference: Iterable[CaseRecord], current: Iterable[CaseRecord]) -> tuple[DistributionShift, ...]:
        """Compare field distributions with PSI and JSD and emit configured alerts."""
        baseline, incoming = tuple(reference), tuple(current)
        if not baseline or not incoming:
            raise ValueError("reference and current cohorts must both be non-empty")
        results: list[DistributionShift] = []
        for field in self.fields:
            base_counts = Counter(str(value) if value is not None else "<missing>"
                                  for row in baseline for value in [getattr(row, field)])
            current_counts = Counter(str(value) if value is not None else "<missing>"
                                     for row in incoming for value in [getattr(row, field)])
            categories = tuple(sorted(set(base_counts) | set(current_counts)))
            base_prop = _normalize(base_counts, categories, self.smoothing)
            current_prop = _normalize(current_counts, categories, self.smoothing)
            psi_value = _psi(base_prop, current_prop)
            jsd_value = _jsd(base_prop, current_prop)
            findings: list[Finding] = []
            severity = Severity.ERROR if psi_value >= self.psi_error else (
                Severity.WARNING if psi_value >= self.psi_warning else None)
            if severity:
                findings.append(Finding(
                    code="COHORT_DISTRIBUTION_SHIFT", severity=severity,
                    message=f"Distribution for '{field}' changed (PSI={psi_value:.4f}).",
                    evidence={"field": field, "psi": round(psi_value, 6),
                              "jsd": round(jsd_value, 6), "threshold": self.psi_error if severity == Severity.ERROR else self.psi_warning},
                ))
            if len(baseline) < self.minimum_records or len(incoming) < self.minimum_records:
                findings.append(Finding(code="DRIFT_SAMPLE_COUNT_LOW", severity=Severity.WARNING,
                                        message=f"Cohort has fewer than {self.minimum_records} records; shift estimates are unstable.",
                                        evidence={"reference_count": len(baseline), "current_count": len(incoming)}))
            results.append(DistributionShift(field, len(baseline), len(incoming), categories,
                                             base_prop, current_prop, psi_value, jsd_value, tuple(findings)))
        return tuple(results)

    @staticmethod
    def summary(shifts: Iterable[DistributionShift]) -> dict[str, object]:
        """Aggregate field-level drift results without individual records."""
        rows = tuple(shifts)
        return {
            "field_count": len(rows),
            "shifted_field_count": sum(bool(row.findings and row.findings[0].code == "COHORT_DISTRIBUTION_SHIFT") for row in rows),
            "max_psi": max((row.population_stability_index for row in rows), default=0.0),
            "fields": [row.to_dict() for row in rows],
        }

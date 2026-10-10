"""Cohort composition and partition balance summaries."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

from cohortseal.models import CaseRecord, Finding, Severity


@dataclass(frozen=True, slots=True)
class CategoryCount:
    """Case and patient counts for one categorical value."""

    field: str
    value: str
    cases: int
    patients: int

    def as_dict(self) -> dict[str, str | int]:
        """Return JSON-compatible values."""
        return {"field": self.field, "value": self.value, "cases": self.cases, "patients": self.patients}


@dataclass(frozen=True, slots=True)
class SplitProfile:
    """Counts by split and selected strata for a manifest snapshot."""

    total_cases: int
    total_patients: int
    split_counts: Mapping[str, Mapping[str, int]]
    categories: tuple[CategoryCount, ...]
    findings: tuple[Finding, ...]

    def to_dict(self) -> dict[str, object]:
        """Serialize counts and checks without raw patient identifiers."""
        return {
            "total_cases": self.total_cases,
            "total_patients": self.total_patients,
            "split_counts": {name: dict(counts) for name, counts in sorted(self.split_counts.items())},
            "categories": [category.as_dict() for category in self.categories],
            "findings": [item.model_dump(mode="json") for item in self.findings],
        }


class CohortProfiler:
    """Summarize sites, labels, modalities, and split sizes."""

    def __init__(self, *, fields: tuple[str, ...] = ("label", "site", "modality"),
                 minimum_patients_per_split: int = 1) -> None:
        if minimum_patients_per_split < 1:
            raise ValueError("minimum_patients_per_split must be positive")
        invalid = set(fields) - {"label", "site", "modality"}
        if invalid:
            raise ValueError(f"unsupported profile fields: {sorted(invalid)}")
        self.fields = fields
        self.minimum_patients_per_split = minimum_patients_per_split

    def profile(self, cases: Iterable[CaseRecord]) -> SplitProfile:
        """Compute aggregate cohort statistics and split-coverage findings."""
        rows = tuple(cases)
        patient_groups: dict[str, list[CaseRecord]] = defaultdict(list)
        for row in rows:
            patient_groups[row.patient_id].append(row)
        split_cases: dict[str, set[str]] = defaultdict(set)
        split_patients: dict[str, set[str]] = defaultdict(set)
        category_rows: dict[tuple[str, str], list[CaseRecord]] = defaultdict(list)
        for row in rows:
            if row.split:
                split_cases[row.split].add(row.case_id)
                split_patients[row.split].add(row.patient_id)
            for field in self.fields:
                value = getattr(row, field)
                category_rows[(field, str(value) if value is not None else "<missing>")].append(row)
        counts = {
            name: {"cases": len(split_cases[name]), "patients": len(split_patients[name])}
            for name in sorted(set(split_cases) | set(split_patients))
        }
        categories = tuple(
            CategoryCount(field=field, value=value, cases=len(members),
                          patients=len({row.patient_id for row in members}))
            for (field, value), members in sorted(category_rows.items())
        )
        findings = list(self._check_split_counts(counts))
        findings.extend(self._check_patient_split_consistency(rows))
        findings.extend(self._check_category_coverage(rows))
        return SplitProfile(len(rows), len(patient_groups), counts, categories, tuple(findings))

    def _check_split_counts(self, counts: Mapping[str, Mapping[str, int]]) -> Iterable[Finding]:
        """Warn when a declared split is below the configured patient minimum."""
        for split, values in counts.items():
            if values["patients"] < self.minimum_patients_per_split:
                yield Finding(code="SMALL_SPLIT", severity=Severity.WARNING,
                              message=f"Split '{split}' has only {values['patients']} patient groups.",
                              evidence={"split": split, "patient_count": values["patients"],
                                        "minimum": self.minimum_patients_per_split})

    @staticmethod
    def _check_patient_split_consistency(rows: tuple[CaseRecord, ...]) -> Iterable[Finding]:
        """Flag patients with cross-split rows independently of audit engine use."""
        patient_splits: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            if row.split:
                patient_splits[row.patient_id].add(row.split)
        count = sum(len(splits) > 1 for splits in patient_splits.values())
        if count:
            yield Finding(code="PROFILE_PATIENT_CROSS_SPLIT", severity=Severity.ERROR,
                          message=f"{count} patient groups appear in more than one split.",
                          evidence={"patient_group_count": count})

    def _check_category_coverage(self, rows: tuple[CaseRecord, ...]) -> Iterable[Finding]:
        """Report strata that do not occur in every declared split."""
        declared_splits = {row.split for row in rows if row.split}
        if len(declared_splits) < 2:
            return
        for field in self.fields:
            values = {str(getattr(row, field)) for row in rows if getattr(row, field) is not None}
            for value in sorted(values):
                present = {row.split for row in rows if str(getattr(row, field)) == value and row.split}
                absent = sorted(declared_splits - present)
                if absent:
                    yield Finding(code="STRATUM_MISSING_FROM_SPLIT", severity=Severity.WARNING,
                                  message=f"Value '{value}' for '{field}' is absent from {len(absent)} split(s).",
                                  evidence={"field": field, "value": value, "absent_splits": absent})


def compare_profiles(before: SplitProfile, after: SplitProfile) -> dict[str, object]:
    """Return a compact numeric comparison between two cohort snapshots."""
    fields = sorted(set(before.split_counts) | set(after.split_counts))
    split_delta: dict[str, dict[str, int]] = {}
    for split in fields:
        old = before.split_counts.get(split, {"cases": 0, "patients": 0})
        new = after.split_counts.get(split, {"cases": 0, "patients": 0})
        split_delta[split] = {key: int(new.get(key, 0) - old.get(key, 0)) for key in ("cases", "patients")}
    return {
        "case_delta": after.total_cases - before.total_cases,
        "patient_delta": after.total_patients - before.total_patients,
        "split_deltas": split_delta,
        "new_error_count": sum(item.severity == Severity.ERROR for item in after.findings),
    }

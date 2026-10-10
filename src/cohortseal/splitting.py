"""Deterministic patient-group split construction and validation."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from cohortseal.errors import SplitError
from cohortseal.models import CaseRecord, SplitAssignment


@dataclass(frozen=True, slots=True)
class SplitPlan:
    """Immutable split plan with seed and constraints for reproducibility."""

    assignments: tuple[SplitAssignment, ...]
    fractions: Mapping[str, float]
    seed: int
    stratify_by: tuple[str, ...]
    digest: str

    def apply(self, cases: Sequence[CaseRecord]) -> list[CaseRecord]:
        """Return cloned cases with assignments applied by patient identifier."""
        mapping = {item.patient_id: item.split for item in self.assignments}
        missing = sorted({case.patient_id for case in cases} - mapping.keys())
        if missing:
            raise SplitError(f"split plan has no assignment for {len(missing)} patient groups")
        return [case.model_copy(update={"split": mapping[case.patient_id]}) for case in cases]


def _group_signature(rows: list[CaseRecord], fields: tuple[str, ...]) -> tuple[str, ...]:
    """Reduce each patient's cases to a stable multi-label stratum signature."""
    values: list[str] = []
    for field in fields:
        observed = sorted({str(getattr(row, field)) for row in rows if getattr(row, field) is not None})
        values.append("|".join(observed) if observed else "<missing>")
    return tuple(values)


def make_group_split(
    cases: Sequence[CaseRecord],
    fractions: Mapping[str, float] | None = None,
    *,
    seed: int = 42,
    stratify_by: tuple[str, ...] = ("label",),
    holdout_site: str | None = None,
) -> SplitPlan:
    """Assign all records for each patient to one split.

    Greedy stratification balances patient groups, not slices or patches. ``holdout_site``
    assigns all groups from one institution to ``test`` and is intended for an explicit
    site-held-out experiment, not a substitute for an independent clinical study.
    """
    if not cases:
        raise SplitError("cannot split an empty cohort")
    proportions = dict(fractions or {"train": 0.7, "validation": 0.15, "test": 0.15})
    if len(proportions) < 2 or any(value <= 0 for value in proportions.values()):
        raise SplitError("provide at least two splits with positive fractions")
    total = sum(proportions.values())
    proportions = {key: value / total for key, value in proportions.items()}
    if holdout_site and "test" not in proportions:
        raise SplitError("holdout_site requires a 'test' split")
    allowed = {"label", "site", "modality"}
    if set(stratify_by) - allowed:
        raise SplitError(f"stratify_by fields must be selected from {sorted(allowed)}")

    grouped: dict[str, list[CaseRecord]] = defaultdict(list)
    for case in cases:
        grouped[case.patient_id].append(case)
    rng = random.Random(seed)
    signatures = {patient: _group_signature(rows, stratify_by) for patient, rows in grouped.items()}
    strata: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for patient, signature in signatures.items():
        strata[signature].append(patient)
    target_patients = {name: len(grouped) * fraction for name, fraction in proportions.items()}
    assigned: dict[str, str] = {}
    current = Counter()
    stratum_total = {signature: len(patients) for signature, patients in strata.items()}
    stratum_current: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for signature, patients in sorted(strata.items(), key=lambda pair: (len(pair[1]), pair[0])):
        rng.shuffle(patients)
        for patient in sorted(patients, key=lambda item: len(grouped[item]), reverse=True):
            if holdout_site and any(row.site == holdout_site for row in grouped[patient]):
                destination = "test"
            else:
                candidates = [name for name in proportions if name != "test" or not holdout_site]
                def cost(split: str) -> tuple[float, float, str]:
                    desired_stratum = stratum_total[signature] * proportions[split]
                    stratum_deficit = desired_stratum - stratum_current[signature][split]
                    group_deficit = target_patients[split] - current[split]
                    return (-stratum_deficit, -group_deficit, split)
                destination = min(candidates, key=cost)
            assigned[patient] = destination
            current[destination] += 1
            stratum_current[signature][destination] += 1

    assignments = tuple(
        SplitAssignment(
            patient_id=patient,
            split=assigned[patient],
            case_count=len(grouped[patient]),
            strata=dict(zip(stratify_by, signatures[patient], strict=True)),
        )
        for patient in sorted(grouped)
    )
    if len({row.split for row in assignments}) < 2:
        raise SplitError("split constraints produced fewer than two populated splits")
    if len(grouped) >= len(proportions) and {row.split for row in assignments} != set(proportions):
        raise SplitError("one or more requested splits are empty; adjust cohort size or fractions")
    canonical = {
        "seed": seed,
        "fractions": sorted(proportions.items()),
        "stratify_by": stratify_by,
        "assignments": [(item.patient_id, item.split) for item in assignments],
    }
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    return SplitPlan(assignments, proportions, seed, stratify_by, digest)

"""Reproducible microbenchmark for patient-group boundary correctness and runtime."""

from __future__ import annotations

import statistics
import time
import random

from cohortseal.models import CaseRecord
from cohortseal.splitting import make_group_split


def cohort(patient_count: int = 20_000, cases_per_patient: int = 4) -> list[CaseRecord]:
    """Build repeatable metadata-only cases; no image files are created."""
    return [CaseRecord(case_id=f"c{patient}-{index}", patient_id=f"p{patient}",
                       path=f"synthetic/{patient}/{index}", label=str(patient % 4))
            for patient in range(patient_count) for index in range(cases_per_patient)]


def run(repeats: int = 5) -> None:
    """Run optional sklearn baseline and print median time plus correctness."""
    rows = cohort()
    samples: dict[str, list[float]] = {
        "cohortseal_stratified_group": [],
        "sklearn_group_shuffle": [],
        "row_random_split_negative_control": [],
    }
    outcomes: dict[str, bool] = {}
    for seed in range(repeats):
        started = time.perf_counter()
        plan = make_group_split(rows, seed=seed)
        samples["cohortseal_stratified_group"].append(time.perf_counter() - started)
        assigned = plan.apply(rows)
        seen: dict[str, set[str | None]] = {}
        for item in assigned:
            seen.setdefault(item.patient_id, set()).add(item.split)
        outcomes["cohortseal_stratified_group"] = all(len(value) == 1 for value in seen.values())
        try:
            from sklearn.model_selection import GroupShuffleSplit
        except ImportError:
            continue
        started = time.perf_counter()
        iterator = GroupShuffleSplit(n_splits=1, test_size=0.3, random_state=seed)
        train, test = next(iterator.split(range(len(rows)), groups=[item.patient_id for item in rows]))
        samples["sklearn_group_shuffle"].append(time.perf_counter() - started)
        train_groups = {rows[index].patient_id for index in train}
        test_groups = {rows[index].patient_id for index in test}
        outcomes["sklearn_group_shuffle"] = train_groups.isdisjoint(test_groups)
        started = time.perf_counter()
        rng = random.Random(seed)
        indices = list(range(len(rows)))
        rng.shuffle(indices)
        cut = int(len(indices) * 0.7)
        train_random = {rows[index].patient_id for index in indices[:cut]}
        test_random = {rows[index].patient_id for index in indices[cut:]}
        samples["row_random_split_negative_control"].append(time.perf_counter() - started)
        outcomes["row_random_split_negative_control"] = train_random.isdisjoint(test_random)
    for name, values in samples.items():
        if values:
            print(f"{name}: median_seconds={statistics.median(values):.4f} group_boundary_pass={outcomes[name]}")
    print("Dataset: 20,000 patients x 4 metadata rows; record machine and package versions.")
    print("This microbenchmark does not compare clinical performance or duplicate detection quality.")


if __name__ == "__main__":
    run()

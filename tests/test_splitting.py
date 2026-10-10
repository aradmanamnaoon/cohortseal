"""Deterministic group split tests."""

import pytest

from cohortseal.errors import SplitError
from cohortseal.splitting import make_group_split


def test_group_split_is_deterministic_and_patient_safe(cases):
    """Repeated runs with the same seed have identical assignments."""
    first = make_group_split(cases, seed=17)
    second = make_group_split(cases, seed=17)
    assert first.digest == second.digest
    applied = first.apply(cases)
    groups = {}
    for case in applied:
        groups.setdefault(case.patient_id, set()).add(case.split)
    assert all(len(splits) == 1 for splits in groups.values())


def test_site_holdout_assigns_whole_site(cases):
    """Every patient scanned at the held-out site lands in test."""
    plan = make_group_split(cases, holdout_site="B")
    assignments = {item.patient_id: item.split for item in plan.assignments}
    assert all(assignments[f"p{patient}"] == "test" for patient in range(4, 8))
    assert all(assignments[f"p{patient}"] != "test" for patient in range(0, 4))


def test_split_rejects_empty_and_bad_fractions(cases):
    """Invalid split requests fail with domain-specific errors."""
    with pytest.raises(SplitError):
        make_group_split([])
    with pytest.raises(SplitError):
        make_group_split(cases, fractions={"train": 0, "test": 1})


def test_apply_rejects_unseen_patient(cases):
    """Applying a plan to a changed cohort fails closed."""
    plan = make_group_split(cases)
    changed = cases + [cases[0].model_copy(update={"patient_id": "new"})]
    with pytest.raises(SplitError):
        plan.apply(changed)

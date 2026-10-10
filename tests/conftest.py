"""Shared, entirely synthetic cohort fixtures."""

from __future__ import annotations

import pytest

from cohortseal.models import CaseRecord


@pytest.fixture
def cases() -> list[CaseRecord]:
    """Two slices per patient, with labels and two sites."""
    return [
        CaseRecord(case_id=f"c{patient}-{slice_id}", patient_id=f"p{patient}",
                   path=f"/synthetic/{patient}/{slice_id}.nii.gz", site="A" if patient < 4 else "B",
                   label="positive" if patient % 2 else "negative", content_sha256=f"hash-{patient}-{slice_id}")
        for patient in range(8) for slice_id in range(2)
    ]

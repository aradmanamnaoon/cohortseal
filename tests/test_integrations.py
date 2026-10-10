"""MONAI and Hugging Face adapter contract tests without network access."""

import pytest

from cohortseal.errors import CohortSealError
from cohortseal.integrations.huggingface import HubIntegrationError, fetch_manifest
from cohortseal.integrations.monai import to_monai_datalist, validate_monai_datalist
from cohortseal.splitting import make_group_split


def test_monai_adapter_preserves_group_boundaries(cases):
    """Adapter exports patient IDs and ensures all cases in a patient use one split."""
    plan = make_group_split(cases, seed=4)
    datalist = to_monai_datalist(cases, plan=plan)
    assert validate_monai_datalist(datalist) == []
    seen = {}
    for split, rows in datalist.items():
        for row in rows:
            seen.setdefault(row["patient_id"], set()).add(split)
    assert all(len(values) == 1 for values in seen.values())


def test_monai_validator_rejects_cross_split_patient():
    """Imported MONAI datalists are checked before training."""
    data = {
        "train": [{"case_id": "a", "patient_id": "p1", "image": "a.nii.gz"}],
        "test": [{"case_id": "b", "patient_id": "p1", "image": "b.nii.gz"}],
    }
    assert any("multiple splits" in error for error in validate_monai_datalist(data))


def test_huggingface_adapter_rejects_invalid_filename_without_network():
    """Invalid remote paths fail before optional imports or network requests."""
    with pytest.raises(HubIntegrationError, match="single CSV or JSON"):
        fetch_manifest("owner/dataset", "../private.txt")


def test_monai_optional_transform_error_is_actionable():
    """Missing MONAI remains an optional dependency error, not an import-time failure."""
    from cohortseal.integrations.monai import build_monai_metadata_transforms, MonaiIntegrationError
    try:
        import monai  # noqa: F401
    except ImportError:
        with pytest.raises(MonaiIntegrationError, match="install MONAI"):
            build_monai_metadata_transforms()

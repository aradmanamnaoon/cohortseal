"""Tests for high-risk cohort integrity findings."""

from cohortseal.audit import AuditEngine, ExactDuplicateRule, PatientSplitRule
from cohortseal.models import CaseRecord, Severity


def test_patient_cross_split_is_error(cases):
    """A patient's cases must remain in one split."""
    cases[0] = cases[0].model_copy(update={"split": "train"})
    cases[1] = cases[1].model_copy(update={"split": "test"})
    report = AuditEngine([PatientSplitRule()]).run(cases)
    assert not report.passed
    assert report.findings[0].code == "PATIENT_CROSS_SPLIT"
    assert report.findings[0].severity == Severity.ERROR


def test_identical_content_across_splits_is_error(cases):
    """Exact byte-duplicate hashes across splits are caught."""
    cases[0] = cases[0].model_copy(update={"split": "train", "content_sha256": "same"})
    cases[2] = cases[2].model_copy(update={"split": "test", "content_sha256": "same"})
    report = AuditEngine([ExactDuplicateRule()]).run(cases)
    assert report.findings[0].evidence["split_count"] == 2


def test_audit_summary_does_not_expose_identifiers(cases):
    """Aggregate summaries are safe to log without patient IDs."""
    summary = AuditEngine().run(cases).summary()
    assert "patient_ids" not in summary
    assert summary["patients"] == 8


def test_same_patient_in_same_split_is_valid(cases):
    """Multiple series for a patient inside one split are expected."""
    assigned = [case.model_copy(update={"split": "train"}) for case in cases[:2]]
    assert AuditEngine([PatientSplitRule()]).run(assigned).passed

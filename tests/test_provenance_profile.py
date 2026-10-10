"""Preprocessing declarations and cohort composition tests."""

from cohortseal.profile import CohortProfiler, compare_profiles
from cohortseal.provenance import (
    FitScope, PipelineAuditor, PipelinePhase, PipelineStep, validate_pipeline_dict,
)


def test_pipeline_auditor_catches_fit_before_split():
    """Dataset-level fitting before a split is an error."""
    report = PipelineAuditor().audit([
        PipelineStep("normalizer", PipelinePhase.FIT, data_dependent=True,
                     fit_scope=FitScope.ALL, fitted_before_split=True),
        PipelineStep("split", PipelinePhase.SPLIT),
    ])
    assert not report.passed
    assert {item.code for item in report.findings} >= {"FIT_BEFORE_SPLIT", "NON_TRAIN_FIT_SCOPE", "PIPELINE_PHASE_ORDER"}


def test_pipeline_dict_accepts_train_only_scaler():
    """A fitted train scaler applied to all partitions is represented explicitly."""
    report = validate_pipeline_dict([
        {"name": "split", "phase": "split"},
        {"name": "scale", "phase": "fit", "data_dependent": True,
         "fit_scope": "train", "applied_to": ["train", "validation", "test"]},
    ])
    assert report.passed


def test_profile_emits_aggregate_counts_and_deltas(cases):
    """Profile output counts patients and can compare snapshots without IDs."""
    assigned = [case.model_copy(update={"split": "train" if i < 8 else "test"})
                for i, case in enumerate(cases)]
    before = CohortProfiler().profile(assigned)
    after = CohortProfiler().profile(assigned[:-1])
    delta = compare_profiles(before, after)
    assert before.total_patients == 8
    assert delta["case_delta"] == -1
    assert "patient_ids" not in before.to_dict()

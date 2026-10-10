"""Derived-data lineage and cohort distribution shift tests."""

from cohortseal.cohort_drift import CohortDriftMonitor
from cohortseal.lineage import LineageGraph
from cohortseal.models import CaseRecord, Severity


def test_lineage_cross_split_and_cycle_findings():
    """A child must share patient/split context and graph must remain acyclic."""
    cases = [
        CaseRecord(case_id="parent", patient_id="p1", path="p.nii.gz", split="train"),
        CaseRecord(case_id="child", patient_id="p1", path="c.nii.gz", split="test",
                   metadata={"parent_case_id": "parent", "transform": "crop"}),
        CaseRecord(case_id="loop", patient_id="p2", path="l.nii.gz",
                   metadata={"parent_case_id": "loop"}),
    ]
    report = LineageGraph().audit(cases)
    codes = {item.code for item in report.findings}
    assert "LINEAGE_CROSS_SPLIT" in codes
    assert "SELF_LINEAGE_EDGE" in codes


def test_drift_monitor_emits_shift_and_small_sample_warning(cases):
    """Substantially different site composition is surfaced with aggregate evidence."""
    base = [case.model_copy(update={"site": "A"}) for case in cases]
    current = [case.model_copy(update={"site": "B"}) for case in cases]
    result = CohortDriftMonitor(fields=("site",), minimum_records=30).compare(base, current)
    assert result[0].population_stability_index > 0.25
    assert any(item.severity == Severity.ERROR for item in result[0].findings)
    assert any(item.code == "DRIFT_SAMPLE_COUNT_LOW" for item in result[0].findings)

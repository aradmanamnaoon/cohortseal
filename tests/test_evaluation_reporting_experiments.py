"""Evaluation, safe report rendering, and experiment lifecycle integration tests."""

import pytest

from cohortseal.evaluation import BinaryPrediction, binary_classification_metrics, patient_cluster_bootstrap
from cohortseal.experiments import ExperimentRegistry, ExperimentSpec, ExperimentStatus, compare_experiments
from cohortseal.profile import CohortProfiler
from cohortseal.reporting import ReportBuilder
from cohortseal.audit import AuditEngine
from cohortseal.storage import RunStore


def test_binary_metrics_and_cluster_bootstrap():
    """Metrics are tie-aware and bootstrap resamples patient groups."""
    rows = [
        BinaryPrediction("c1", "p1", 1, .9), BinaryPrediction("c2", "p1", 1, .7),
        BinaryPrediction("c3", "p2", 0, .2), BinaryPrediction("c4", "p2", 0, .1),
        BinaryPrediction("c5", "p3", 1, .6), BinaryPrediction("c6", "p4", 0, .4),
    ]
    result = binary_classification_metrics(rows)
    assert result.auroc == 1.0
    interval = patient_cluster_bootstrap(rows, repeats=100, seed=7)
    assert interval.cluster_count == 4
    assert interval.lower <= interval.estimate <= interval.upper


def test_report_html_escapes_untrusted_values(cases):
    """Labels and messages cannot inject executable markup into HTML output."""
    rows = [case.model_copy(update={"site": "<script>alert(1)</script>"}) for case in cases]
    audit = AuditEngine().run(rows)
    profile = CohortProfiler().profile(rows)
    builder = ReportBuilder(title="<img src=x onerror=alert(1)>")
    payload = builder.build_payload(audit, profile, dataset_name="demo")
    output = builder.render_html(payload)
    assert "<script>alert(1)</script>" not in output
    assert "&lt;script&gt;" in output


def test_experiment_lifecycle_and_secret_redaction(tmp_path):
    """Registry persists reproducibility digests and legal status transitions."""
    store = RunStore(tmp_path / "experiment.db")
    registry = ExperimentRegistry(store)
    spec = ExperimentSpec("unet-baseline", "a" * 64, "b" * 64, "monai-unet",
                          pipeline_digest="c" * 64,
                          config={"learning_rate": 0.001, "api_token": "do-not-store"})
    first = registry.create(spec)
    assert first.config["api_token"] == "<redacted>"
    running = registry.transition(first.experiment_id, ExperimentStatus.RUNNING)
    completed = registry.transition(running.experiment_id, ExperimentStatus.COMPLETED)
    assert completed.status == ExperimentStatus.COMPLETED
    assert len(completed.events) == 3
    assert compare_experiments(first, completed)["reproducible_inputs_match"] is True
    with pytest.raises(Exception, match="not allowed"):
        registry.transition(completed.experiment_id, ExperimentStatus.RUNNING)


def test_segmentation_metrics_empty_masks():
    """Empty-mask overlap semantics are explicit and deterministic."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    from cohortseal.evaluation import binary_segmentation_metrics
    result = binary_segmentation_metrics(np.zeros((3, 3)), np.zeros((3, 3)))
    assert result.dice == 1.0 and result.jaccard == 1.0
    assert result.hausdorff95_mm is None

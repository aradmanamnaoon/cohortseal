"""Descriptive evaluation metrics for cohort-level medical imaging experiments.

These functions produce statistical summaries, not diagnostic claims. Thresholds,
confidence intervals, and subgroup definitions must be prespecified by study authors.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from cohortseal.errors import CohortSealError


class EvaluationError(CohortSealError):
    """Invalid predictions or incompatible reference and prediction arrays."""


@dataclass(frozen=True, slots=True)
class BinaryPrediction:
    """One binary classification prediction associated with a patient group."""

    case_id: str
    patient_id: str
    y_true: int
    y_score: float
    site: str | None = None

    def __post_init__(self) -> None:
        """Validate binary labels and finite probability scores."""
        if not self.case_id.strip() or not self.patient_id.strip():
            raise ValueError("case_id and patient_id must not be blank")
        if self.y_true not in (0, 1):
            raise ValueError("y_true must be 0 or 1")
        if not math.isfinite(self.y_score) or not 0 <= self.y_score <= 1:
            raise ValueError("y_score must be a finite probability in [0, 1]")


@dataclass(frozen=True, slots=True)
class MetricSummary:
    """Binary classification metrics and sample counts."""

    n_cases: int
    n_patients: int
    positives: int
    negatives: int
    threshold: float
    sensitivity: float | None
    specificity: float | None
    precision: float | None
    negative_predictive_value: float | None
    accuracy: float | None
    balanced_accuracy: float | None
    auroc: float | None
    brier_score: float | None
    expected_calibration_error: float | None
    confusion: dict[str, int]

    def to_dict(self) -> dict[str, int | float | None | dict[str, int]]:
        """Convert metrics to a JSON-friendly mapping."""
        return {
            "n_cases": self.n_cases, "n_patients": self.n_patients,
            "positives": self.positives, "negatives": self.negatives,
            "threshold": self.threshold, "sensitivity": self.sensitivity,
            "specificity": self.specificity, "precision": self.precision,
            "negative_predictive_value": self.negative_predictive_value,
            "accuracy": self.accuracy, "balanced_accuracy": self.balanced_accuracy,
            "auroc": self.auroc, "brier_score": self.brier_score,
            "expected_calibration_error": self.expected_calibration_error,
            "confusion": dict(self.confusion),
        }


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return a ratio or ``None`` when its denominator is undefined."""
    return numerator / denominator if denominator else None


def _auroc(rows: Sequence[BinaryPrediction]) -> float | None:
    """Compute exact tie-aware ROC AUC by the Mann-Whitney rank identity."""
    positives = sum(row.y_true == 1 for row in rows)
    negatives = len(rows) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(rows, key=lambda item: item.y_score)
    positive_rank_sum = 0.0
    offset = 0
    while offset < len(ordered):
        end = offset + 1
        while end < len(ordered) and ordered[end].y_score == ordered[offset].y_score:
            end += 1
        average_rank = ((offset + 1) + end) / 2
        positive_rank_sum += average_rank * sum(item.y_true == 1 for item in ordered[offset:end])
        offset = end
    return (positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _ece(rows: Sequence[BinaryPrediction], bins: int) -> float:
    """Calculate fixed-width expected calibration error."""
    counts = [0] * bins
    score_sum = [0.0] * bins
    label_sum = [0] * bins
    for row in rows:
        index = min(int(row.y_score * bins), bins - 1)
        counts[index] += 1
        score_sum[index] += row.y_score
        label_sum[index] += row.y_true
    total = len(rows)
    return sum(
        counts[index] / total * abs(score_sum[index] / counts[index] - label_sum[index] / counts[index])
        for index in range(bins) if counts[index]
    )


def binary_classification_metrics(
    predictions: Iterable[BinaryPrediction], *, threshold: float = 0.5, calibration_bins: int = 10
) -> MetricSummary:
    """Compute AUROC, threshold metrics, Brier score, and fixed-bin calibration error."""
    if not 0 <= threshold <= 1 or not math.isfinite(threshold):
        raise ValueError("threshold must be a finite value in [0, 1]")
    if calibration_bins < 1:
        raise ValueError("calibration_bins must be positive")
    rows = tuple(predictions)
    if not rows:
        raise EvaluationError("at least one prediction is required")
    seen: set[str] = set()
    for row in rows:
        if row.case_id in seen:
            raise EvaluationError(f"duplicate case_id '{row.case_id}'")
        seen.add(row.case_id)
    tp = sum(item.y_true == 1 and item.y_score >= threshold for item in rows)
    tn = sum(item.y_true == 0 and item.y_score < threshold for item in rows)
    fp = sum(item.y_true == 0 and item.y_score >= threshold for item in rows)
    fn = sum(item.y_true == 1 and item.y_score < threshold for item in rows)
    sensitivity = _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    precision = _ratio(tp, tp + fp)
    npv = _ratio(tn, tn + fn)
    accuracy = (tp + tn) / len(rows)
    balanced = (sensitivity + specificity) / 2 if sensitivity is not None and specificity is not None else None
    brier = sum((item.y_score - item.y_true) ** 2 for item in rows) / len(rows)
    return MetricSummary(
        n_cases=len(rows), n_patients=len({item.patient_id for item in rows}),
        positives=tp + fn, negatives=tn + fp, threshold=threshold,
        sensitivity=sensitivity, specificity=specificity, precision=precision,
        negative_predictive_value=npv, accuracy=accuracy, balanced_accuracy=balanced,
        auroc=_auroc(rows), brier_score=brier,
        expected_calibration_error=_ece(rows, calibration_bins),
        confusion={"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn},
    )


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    """Percentile interval with bootstrap and cluster counts."""

    estimate: float
    lower: float
    upper: float
    confidence: float
    repeats: int
    cluster_count: int


def patient_cluster_bootstrap(
    predictions: Sequence[BinaryPrediction], *, metric: str = "auroc", repeats: int = 1000,
    confidence: float = 0.95, seed: int = 42, threshold: float = 0.5,
) -> ConfidenceInterval:
    """Estimate a percentile interval by resampling patient groups with replacement.

    Every selected cluster contributes all of its cases. Patients sampled more than
    once are copied with unique bootstrap case IDs so metric validation remains strict.
    Undefined metric replicates are discarded; the returned ``repeats`` field reports
    usable replicates. If fewer than two clusters exist, the call fails explicitly.
    """
    if repeats < 100:
        raise ValueError("repeats must be at least 100 for a useful bootstrap")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    if metric not in {"auroc", "sensitivity", "specificity", "accuracy", "balanced_accuracy", "brier_score"}:
        raise ValueError("unsupported bootstrap metric")
    groups: dict[str, list[BinaryPrediction]] = defaultdict(list)
    for row in predictions:
        groups[row.patient_id].append(row)
    patient_ids = sorted(groups)
    if len(patient_ids) < 2:
        raise EvaluationError("patient-cluster bootstrap requires at least two patient groups")
    point = getattr(binary_classification_metrics(predictions, threshold=threshold), metric)
    if point is None:
        raise EvaluationError(f"metric '{metric}' is undefined on the observed cohort")
    rng = random.Random(seed)
    values: list[float] = []
    for repeat in range(repeats):
        sample: list[BinaryPrediction] = []
        for draw, patient in enumerate(rng.choices(patient_ids, k=len(patient_ids))):
            for case_index, row in enumerate(groups[patient]):
                sample.append(BinaryPrediction(
                    case_id=f"boot-{repeat}-{draw}-{case_index}", patient_id=f"boot-{draw}-{patient}",
                    y_true=row.y_true, y_score=row.y_score, site=row.site,
                ))
        value = getattr(binary_classification_metrics(sample, threshold=threshold), metric)
        if value is not None and math.isfinite(value):
            values.append(float(value))
    if len(values) < repeats * 0.5:
        raise EvaluationError("too many bootstrap replicates had undefined metrics")
    values.sort()
    alpha = (1 - confidence) / 2
    lower = values[max(0, math.floor(alpha * len(values)))]
    upper = values[min(len(values) - 1, math.ceil((1 - alpha) * len(values)) - 1)]
    return ConfidenceInterval(float(point), lower, upper, confidence, len(values), len(patient_ids))


def subgroup_metrics(predictions: Iterable[BinaryPrediction], *, field: str = "site",
                     threshold: float = 0.5) -> dict[str, MetricSummary]:
    """Compute comparable binary metrics for each site or patient subgroup."""
    if field != "site":
        raise ValueError("only the site field is supported for stratified predictions")
    groups: dict[str, list[BinaryPrediction]] = defaultdict(list)
    for item in predictions:
        groups[item.site or "<missing>"].append(item)
    return {name: binary_classification_metrics(rows, threshold=threshold)
            for name, rows in sorted(groups.items())}


@dataclass(frozen=True, slots=True)
class SegmentationSummary:
    """Binary segmentation overlap and boundary metrics."""

    dice: float
    jaccard: float
    hausdorff95_mm: float | None
    reference_voxels: int
    predicted_voxels: int

    def to_dict(self) -> dict[str, float | int | None]:
        """Serialize segmentation metrics."""
        return {"dice": self.dice, "jaccard": self.jaccard,
                "hausdorff95_mm": self.hausdorff95_mm,
                "reference_voxels": self.reference_voxels,
                "predicted_voxels": self.predicted_voxels}


def binary_segmentation_metrics(reference: object, prediction: object,
                                spacing_mm: Sequence[float] | None = None) -> SegmentationSummary:
    """Compute binary Dice, Jaccard, and symmetric 95th percentile surface distance.

    Inputs are converted to boolean NumPy arrays. Both-empty masks receive Dice/Jaccard
    of 1.0 and an undefined distance. Exactly one empty mask receives zero overlap and
    an undefined distance because a finite surface distance is not informative.
    """
    try:
        import numpy as np
        from scipy.ndimage import binary_erosion, distance_transform_edt
    except ImportError as exc:
        raise EvaluationError("install cohortseal[metrics] for segmentation metrics") from exc
    truth = np.asarray(reference, dtype=bool)
    pred = np.asarray(prediction, dtype=bool)
    if truth.shape != pred.shape or truth.ndim not in (2, 3):
        raise EvaluationError("reference and prediction must have identical 2D or 3D shapes")
    if spacing_mm is None:
        spacing = tuple(1.0 for _ in range(truth.ndim))
    else:
        spacing = tuple(float(value) for value in spacing_mm)
        if len(spacing) != truth.ndim or any(not math.isfinite(value) or value <= 0 for value in spacing):
            raise ValueError("spacing_mm must contain one positive finite value per array dimension")
    truth_count = int(truth.sum())
    pred_count = int(pred.sum())
    intersection = int(np.logical_and(truth, pred).sum())
    total = truth_count + pred_count
    dice = 1.0 if total == 0 else 2 * intersection / total
    union = truth_count + pred_count - intersection
    jaccard = 1.0 if union == 0 else intersection / union
    distance: float | None = None
    if truth_count and pred_count:
        structure = np.ones((3,) * truth.ndim, dtype=bool)
        truth_surface = np.logical_xor(truth, binary_erosion(truth, structure=structure, border_value=0))
        pred_surface = np.logical_xor(pred, binary_erosion(pred, structure=structure, border_value=0))
        dist_to_truth = distance_transform_edt(~truth_surface, sampling=spacing)[pred_surface]
        dist_to_pred = distance_transform_edt(~pred_surface, sampling=spacing)[truth_surface]
        distance = float(np.percentile(np.concatenate((dist_to_truth, dist_to_pred)), 95))
    return SegmentationSummary(float(dice), float(jaccard), distance, truth_count, pred_count)

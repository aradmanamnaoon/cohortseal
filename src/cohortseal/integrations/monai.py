"""MONAI adapters that preserve explicit patient-group assignments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from cohortseal.errors import CohortSealError
from cohortseal.models import CaseRecord
from cohortseal.splitting import SplitPlan, make_group_split


class MonaiIntegrationError(CohortSealError):
    """MONAI-specific conversion or optional dependency failure."""


def patient_group_plan(cases: Sequence[CaseRecord], **options: Any) -> SplitPlan:
    """Construct CohortSeal's patient-group plan before materializing MONAI rows."""
    return make_group_split(cases, **options)


def to_monai_datalist(
    cases: Iterable[CaseRecord],
    *,
    plan: SplitPlan | None = None,
    label_map: Mapping[str, str] | None = None,
    include_group_metadata: bool = True,
    path_root: str | Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Convert records to MONAI-style train/validation/test dictionaries.

    ``patient_id`` is included only when explicitly requested, allowing projects to
    remove it before passing dictionaries to training code. If a plan is supplied,
    its assignments override manifest split values after patient-safe validation.
    """
    rows = list(cases)
    if plan is not None:
        try:
            rows = plan.apply(rows)
        except Exception as exc:
            raise MonaiIntegrationError(f"split plan does not match MONAI records: {exc}") from exc
    assignments: dict[str, set[str]] = {}
    for row in rows:
        if row.split:
            assignments.setdefault(row.patient_id, set()).add(row.split)
    cross_split = [patient for patient, values in assignments.items() if len(values) > 1]
    if cross_split:
        raise MonaiIntegrationError(f"refusing MONAI conversion: {len(cross_split)} patient groups cross splits")
    root = Path(path_root).expanduser() if path_root is not None else None
    output: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    for row in rows:
        destination = row.split or "train"
        if destination not in output:
            raise MonaiIntegrationError(f"unsupported split name '{destination}'")
        image_path = Path(row.path).expanduser()
        if root is not None and not image_path.is_absolute():
            image_path = root / image_path
        item: dict[str, Any] = {"image": str(image_path), "case_id": row.case_id}
        label_path = label_map.get(row.case_id) if label_map else None
        if label_path:
            label_value = Path(label_path).expanduser()
            if root is not None and not label_value.is_absolute():
                label_value = root / label_value
            item["label"] = str(label_value)
        if include_group_metadata:
            item["patient_id"] = row.patient_id
        if row.site:
            item["site"] = row.site
        if row.modality:
            item["modality"] = row.modality
        output[destination].append(item)
    return output


def write_monai_datalist(
    cases: Iterable[CaseRecord],
    output_path: str | Path,
    *,
    plan: SplitPlan | None = None,
    label_map: Mapping[str, str] | None = None,
    include_group_metadata: bool = True,
) -> Path:
    """Write a deterministic JSON datalist that MONAI bundle workflows can consume."""
    import json

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = to_monai_datalist(cases, plan=plan, label_map=label_map,
                             include_group_metadata=include_group_metadata)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def build_monai_metadata_transforms(
    *,
    image_key: str = "image",
    label_key: str = "label",
    spatial_size: tuple[int, int, int] | None = None,
    pixdim: tuple[float, float, float] | None = None,
    modality: str = "MRI",
) -> Any:
    """Build a minimal MONAI transform chain while leaving fitted normalization explicit.

    The returned transform loads arrays, fixes channel order, and optionally normalizes
    orientation and spacing. It intentionally does not estimate dataset-level intensity
    statistics. Fit any data-dependent scaler on training cases only, after splitting.
    """
    try:
        from monai.transforms import Compose, EnsureChannelFirstd, LoadImaged, Orientationd, Spacingd
    except ImportError as exc:
        raise MonaiIntegrationError("install MONAI to build transform chains") from exc
    keys = [image_key, label_key]
    transforms: list[Any] = [LoadImaged(keys=keys, image_only=False),
                             EnsureChannelFirstd(keys=keys)]
    if spatial_size is not None:
        if any(size <= 0 for size in spatial_size):
            raise ValueError("spatial_size values must be positive")
        transforms.append(Orientationd(keys=keys, axcodes="RAS"))
    if pixdim is not None:
        if any(size <= 0 for size in pixdim):
            raise ValueError("pixdim values must be positive")
        transforms.append(Spacingd(keys=keys, pixdim=pixdim, mode=("bilinear", "nearest")))
    if modality.strip().upper() not in {"CT", "MRI", "MR", "PET", "US", "XR", "OTHER"}:
        raise ValueError(f"unrecognized modality '{modality}'")
    return Compose(transforms)


def validate_monai_datalist(datalist: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
    """Return deterministic structural errors for a MONAI split mapping."""
    errors: list[str] = []
    known = {"train", "validation", "test"}
    unknown = set(datalist) - known
    if unknown:
        errors.append(f"unsupported split keys: {sorted(unknown)}")
    patient_splits: dict[str, set[str]] = {}
    case_ids: set[str] = set()
    for split, items in datalist.items():
        if not isinstance(items, Sequence):
            errors.append(f"split '{split}' must contain a sequence")
            continue
        for index, item in enumerate(items):
            if not isinstance(item, Mapping) or not item.get("image"):
                errors.append(f"{split}[{index}] must be a mapping with an image path")
                continue
            case_id = str(item.get("case_id", "")).strip()
            if case_id and case_id in case_ids:
                errors.append(f"duplicate case_id '{case_id}'")
            case_ids.add(case_id)
            patient = str(item.get("patient_id", "")).strip()
            if patient:
                patient_splits.setdefault(patient, set()).add(split)
    for patient, splits in sorted(patient_splits.items()):
        if len(splits) > 1:
            errors.append(f"patient group '{patient}' appears in multiple splits: {sorted(splits)}")
    return errors

"""Local experiment registry for reproducible cohort/split/preprocessing snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from cohortseal.errors import CohortSealError
from cohortseal.storage import RunStore


class ExperimentError(CohortSealError):
    """Invalid experiment specification or lifecycle transition."""


class ExperimentStatus(str, Enum):
    """Lifecycle state stored for an experiment."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


_TRANSITIONS: dict[ExperimentStatus, frozenset[ExperimentStatus]] = {
    ExperimentStatus.CREATED: frozenset({ExperimentStatus.RUNNING, ExperimentStatus.ARCHIVED}),
    ExperimentStatus.RUNNING: frozenset({ExperimentStatus.COMPLETED, ExperimentStatus.FAILED}),
    ExperimentStatus.FAILED: frozenset({ExperimentStatus.RUNNING, ExperimentStatus.ARCHIVED}),
    ExperimentStatus.COMPLETED: frozenset({ExperimentStatus.ARCHIVED}),
    ExperimentStatus.ARCHIVED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """Immutable experiment identity based on cohort, split, pipeline, and model."""

    name: str
    dataset_digest: str
    split_digest: str
    model_family: str
    pipeline_digest: str | None = None
    config: Mapping[str, Any] | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate identifiers and SHA-256 digest shapes."""
        if not self.name.strip() or not self.model_family.strip():
            raise ValueError("experiment name and model_family must not be blank")
        for field_name, value in (("dataset_digest", self.dataset_digest),
                                  ("split_digest", self.split_digest),
                                  ("pipeline_digest", self.pipeline_digest)):
            if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                raise ValueError(f"{field_name} must be a 64-character SHA-256 digest")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must be unique")

    @property
    def config_digest(self) -> str:
        """Hash non-secret canonicalized configuration for comparison."""
        redacted = redact_config(dict(self.config or {}))
        encoded = json.dumps(redacted, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """Typed experiment registry record."""

    experiment_id: str
    name: str
    status: ExperimentStatus
    dataset_digest: str
    split_digest: str
    pipeline_digest: str | None
    model_family: str
    config: Mapping[str, Any]
    tags: tuple[str, ...]
    created_at: str
    updated_at: str
    events: tuple[Mapping[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExperimentRecord":
        """Validate and convert a database row with decoded JSON columns."""
        try:
            return cls(
                experiment_id=str(payload["experiment_id"]), name=str(payload["name"]),
                status=ExperimentStatus(str(payload["status"])),
                dataset_digest=str(payload["dataset_digest"]), split_digest=str(payload["split_digest"]),
                pipeline_digest=str(payload["pipeline_digest"]) if payload.get("pipeline_digest") else None,
                model_family=str(payload["model_family"]), config=dict(payload.get("config", {})),
                tags=tuple(payload.get("tags", ())), created_at=str(payload.get("created_at", "")),
                updated_at=str(payload.get("updated_at", "")),
                events=tuple(payload.get("events", ())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExperimentError(f"invalid stored experiment record: {exc}") from exc


def redact_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively replace secret-like configuration values before persistence."""
    secret_pattern = re.compile(r"(secret|token|password|credential|api[_-]?key|private[_-]?key)", re.I)
    result: dict[str, Any] = {}
    for key, value in config.items():
        name = str(key)
        if secret_pattern.search(name):
            result[name] = "<redacted>"
        elif isinstance(value, Mapping):
            result[name] = redact_config(value)
        elif isinstance(value, (list, tuple)):
            result[name] = [redact_config(item) if isinstance(item, Mapping) else item for item in value]
        elif value is None or isinstance(value, (str, int, float, bool)):
            result[name] = value
        else:
            result[name] = str(value)
    return result


class ExperimentRegistry:
    """Store immutable experiment metadata and append-only state transitions."""

    def __init__(self, store: RunStore) -> None:
        self.store = store

    def create(self, spec: ExperimentSpec) -> ExperimentRecord:
        """Register an experiment and persist redacted configuration."""
        experiment_id = str(uuid.uuid4())
        self.store.create_experiment(
            experiment_id, spec.name.strip(), spec.dataset_digest.lower(), spec.split_digest.lower(),
            spec.pipeline_digest.lower() if spec.pipeline_digest else None,
            spec.model_family.strip(), redact_config(dict(spec.config or {})), list(spec.tags),
        )
        record = self.get(experiment_id)
        if record is None:
            raise ExperimentError("experiment was inserted but could not be read back")
        return record

    def get(self, experiment_id: str) -> ExperimentRecord | None:
        """Fetch one record or return ``None`` when it does not exist."""
        payload = self.store.get_experiment(experiment_id)
        return ExperimentRecord.from_dict(payload) if payload else None

    def list(self, *, limit: int = 50, status: ExperimentStatus | None = None) -> tuple[ExperimentRecord, ...]:
        """List experiment summaries ordered by registration time."""
        rows = self.store.list_experiments(limit, status=status.value if status else None)
        return tuple(ExperimentRecord.from_dict(row) for row in rows)

    def transition(self, experiment_id: str, target: ExperimentStatus, *, note: str | None = None) -> ExperimentRecord:
        """Advance lifecycle state under a compare-and-swap guard."""
        current = self.get(experiment_id)
        if current is None:
            raise ExperimentError(f"experiment '{experiment_id}' does not exist")
        if target not in _TRANSITIONS[current.status]:
            allowed = sorted(item.value for item in _TRANSITIONS[current.status])
            raise ExperimentError(f"transition {current.status.value}->{target.value} is not allowed; allowed: {allowed}")
        changed = self.store.transition_experiment(experiment_id, current.status.value,
                                                  target.value, note=note)
        if not changed:
            raise ExperimentError("experiment state changed concurrently; reload and retry")
        record = self.get(experiment_id)
        if record is None:
            raise ExperimentError("experiment disappeared after a successful transition")
        return record


def compare_experiments(left: ExperimentRecord, right: ExperimentRecord) -> dict[str, object]:
    """Compare reproducibility-critical fields without dumping arbitrary config."""
    fields = ("dataset_digest", "split_digest", "pipeline_digest", "model_family", "config")
    differences: dict[str, dict[str, object]] = {}
    for field in fields:
        first, second = getattr(left, field), getattr(right, field)
        if first != second:
            if field == "config":
                first = hashlib.sha256(json.dumps(first, sort_keys=True, default=str).encode()).hexdigest()
                second = hashlib.sha256(json.dumps(second, sort_keys=True, default=str).encode()).hexdigest()
            differences[field] = {"left": first, "right": second}
    return {"reproducible_inputs_match": not differences, "differences": differences,
            "left_id": left.experiment_id, "right_id": right.experiment_id}

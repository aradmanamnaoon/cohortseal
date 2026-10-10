"""Domain models. Identifiers are opaque tokens; image pixels are never loaded here."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(str, Enum):
    """Audit finding severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CaseRecord(BaseModel):
    """One image, series, or derived sample linked to a patient-level group."""

    model_config = ConfigDict(extra="allow", frozen=True)

    case_id: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    split: str | None = None
    site: str | None = None
    label: str | None = None
    modality: str | None = None
    study_id: str | None = None
    series_id: str | None = None
    content_sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("case_id", "patient_id", "path")
    @classmethod
    def strip_required(cls, value: str) -> str:
        """Reject whitespace-only identifiers and normalize surrounding whitespace."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @property
    def resolved_path(self) -> Path:
        """Return path as provided, without accessing its contents."""
        return Path(self.path).expanduser()


class Finding(BaseModel):
    """A machine-readable finding tied to a stable rule identifier."""

    model_config = ConfigDict(frozen=True)

    code: str
    severity: Severity
    message: str
    case_ids: tuple[str, ...] = ()
    evidence: dict[str, Any] = Field(default_factory=dict)


class SplitAssignment(BaseModel):
    """A patient group assigned to one split, preserving a reproducible reason."""

    model_config = ConfigDict(frozen=True)

    patient_id: str
    split: str
    case_count: int = Field(ge=1)
    strata: dict[str, str | None] = Field(default_factory=dict)


class DatasetManifest(BaseModel):
    """Validated dataset cohort and provenance metadata."""

    schema_version: str = "1"
    dataset_name: str
    cases: list[CaseRecord]
    source_uri: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

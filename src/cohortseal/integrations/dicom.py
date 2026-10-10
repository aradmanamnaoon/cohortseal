"""Metadata-only DICOM inspection and pseudonymous manifest generation.

The checks in this module are engineering safeguards, not a determination of HIPAA,
GDPR, or DICOM PS3.15 compliance. Pixel data is never accessed or decoded.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from cohortseal.errors import CohortSealError
from cohortseal.models import CaseRecord, Finding, Severity


class DicomIntegrationError(CohortSealError):
    """DICOM dependencies or file parsing failed."""


_IDENTIFYING_KEYWORDS = frozenset({
    "PatientName", "PatientID", "OtherPatientIDs", "OtherPatientNames",
    "PatientAddress", "PatientTelephoneNumbers", "PatientBirthDate",
    "AccessionNumber", "InstitutionName", "InstitutionAddress",
    "InstitutionalDepartmentName", "ReferringPhysicianName", "PerformingPhysicianName",
    "OperatorsName", "MedicalRecordLocator", "InsurancePlanIdentification",
})


@dataclass(frozen=True, slots=True)
class DicomInspection:
    """Non-identifying result for one file; raw tag values are not included."""

    path_reference: str
    modality: str | None
    study_uid_digest: str | None
    series_uid_digest: str | None
    patient_token: str | None
    findings: tuple[Finding, ...]
    transfer_syntax: str | None
    rows: int | None
    columns: int | None

    def to_dict(self) -> dict[str, object]:
        """Return safe metadata and finding codes without DICOM tag values."""
        return {
            "path_reference": self.path_reference,
            "modality": self.modality,
            "study_uid_digest": self.study_uid_digest,
            "series_uid_digest": self.series_uid_digest,
            "patient_token": self.patient_token,
            "findings": [item.model_dump(mode="json") for item in self.findings],
            "transfer_syntax": self.transfer_syntax,
            "rows": self.rows,
            "columns": self.columns,
        }


@dataclass(frozen=True, slots=True)
class DicomBatchReport:
    """Batch-level DICOM inspection with aggregate counts."""

    files: tuple[DicomInspection, ...]

    @property
    def finding_count(self) -> int:
        """Number of findings across all inspected files."""
        return sum(len(item.findings) for item in self.files)

    @property
    def passed(self) -> bool:
        """Whether no configured high-severity identifier warning was raised."""
        return not any(f.severity == Severity.ERROR for row in self.files for f in row.findings)

    def summary(self) -> dict[str, int | bool]:
        """Return aggregate counts only."""
        return {"passed": self.passed, "files": len(self.files),
                "findings": self.finding_count,
                "error_count": sum(f.severity == Severity.ERROR for row in self.files for f in row.findings),
                "warning_count": sum(f.severity == Severity.WARNING for row in self.files for f in row.findings)}


def _digest(value: str | None, key: bytes) -> str | None:
    """HMAC-tokenize an identifier so dictionary attacks require the local secret."""
    if not value:
        return None
    return hmac.new(key, value.encode("utf-8", errors="replace"), hashlib.sha256).hexdigest()


def _path_reference(path: Path) -> str:
    """Create a stable opaque reference that does not reveal a PHI-bearing filename."""
    normalized = str(path.expanduser().resolve())
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:20]


class DicomInspector:
    """Inspect DICOM headers without decoding pixel arrays or returning PHI values."""

    def __init__(self, *, token_key: bytes, include_private_tag_warning: bool = True,
                 inspect_sequences: bool = True, max_sequence_depth: int = 8) -> None:
        if len(token_key) < 16:
            raise ValueError("token_key must contain at least 16 bytes")
        if max_sequence_depth < 0:
            raise ValueError("max_sequence_depth must be non-negative")
        self._token_key = token_key
        self.include_private_tag_warning = include_private_tag_warning
        self.inspect_sequences = inspect_sequences
        self.max_sequence_depth = max_sequence_depth

    def inspect(self, path: str | Path) -> DicomInspection:
        """Read a single file's header and emit redacted identifier findings."""
        try:
            import pydicom
        except ImportError as exc:
            raise DicomIntegrationError("install cohortseal[dicom] to inspect DICOM files") from exc
        source = Path(path)
        try:
            dataset = pydicom.dcmread(source, stop_before_pixels=True, force=False)
        except Exception as exc:
            raise DicomIntegrationError(f"cannot parse DICOM header for file reference {_path_reference(source)}") from None
        findings: list[Finding] = []
        found: set[str] = set()
        self._scan_dataset(dataset, found, depth=0)
        for keyword in sorted(found & _IDENTIFYING_KEYWORDS):
            findings.append(Finding(
                code="DICOM_IDENTIFYING_TAG_PRESENT", severity=Severity.WARNING,
                message=f"Potentially identifying DICOM attribute '{keyword}' is populated.",
                evidence={"keyword": keyword},
            ))
        if self.include_private_tag_warning and "private_tags" in found:
            findings.append(Finding(code="DICOM_PRIVATE_TAGS_PRESENT", severity=Severity.WARNING,
                                    message="Private DICOM elements are present and need profile-specific review."))
        removed = str(getattr(dataset, "PatientIdentityRemoved", "")).strip().upper()
        if removed not in {"YES", "Y", "TRUE", "1"}:
            findings.append(Finding(code="DICOM_DEIDENTIFICATION_FLAG_MISSING", severity=Severity.WARNING,
                                    message="PatientIdentityRemoved is not affirmative; this flag alone is not proof of de-identification."))
        transfer = getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", None)
        return DicomInspection(
            path_reference=_path_reference(source), modality=_text(getattr(dataset, "Modality", None)),
            study_uid_digest=_digest(_text(getattr(dataset, "StudyInstanceUID", None)), self._token_key),
            series_uid_digest=_digest(_text(getattr(dataset, "SeriesInstanceUID", None)), self._token_key),
            patient_token=_digest(_text(getattr(dataset, "PatientID", None)), self._token_key),
            findings=tuple(findings), transfer_syntax=str(transfer) if transfer else None,
            rows=_integer(getattr(dataset, "Rows", None)), columns=_integer(getattr(dataset, "Columns", None)),
        )

    def inspect_many(self, paths: Iterable[str | Path]) -> DicomBatchReport:
        """Inspect paths sequentially with bounded memory and deterministic order."""
        return DicomBatchReport(tuple(self.inspect(path) for path in paths))

    def _scan_dataset(self, dataset: object, found: set[str], *, depth: int) -> None:
        """Collect keyword presence without retaining element values."""
        if depth > self.max_sequence_depth:
            found.add("sequence_depth_limit")
            return
        try:
            elements = list(dataset)  # type: ignore[arg-type]
        except TypeError:
            return
        for element in elements:
            if getattr(element, "is_private", False):
                found.add("private_tags")
            keyword = str(getattr(element, "keyword", ""))
            if keyword in _IDENTIFYING_KEYWORDS and bool(str(getattr(element, "value", "")).strip()):
                found.add(keyword)
            value = getattr(element, "value", None)
            if self.inspect_sequences and getattr(element, "VR", None) == "SQ":
                for item in value or ():
                    self._scan_dataset(item, found, depth=depth + 1)

    def to_case_record(self, inspection: DicomInspection, *, image_path: str | Path,
                       case_id: str | None = None,
                       patient_token: str | None = None, split: str | None = None,
                       site: str | None = None, label: str | None = None) -> CaseRecord:
        """Create a manifest record from inspection output using keyed patient tokens."""
        patient = patient_token or inspection.patient_token
        if not patient:
            raise DicomIntegrationError("DICOM PatientID was absent; supply a verified pseudonymous patient token")
        identifier = case_id or inspection.path_reference
        return CaseRecord(case_id=identifier, patient_id=patient, path=str(image_path), split=split,
                          site=site, label=label, modality=inspection.modality,
                          study_id=inspection.study_uid_digest, series_id=inspection.series_uid_digest,
                          metadata={"source": "dicom", "header_finding_count": len(inspection.findings)})


def _text(value: object) -> str | None:
    """Normalize a metadata scalar without surfacing it in errors."""
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _integer(value: object) -> int | None:
    """Convert a positive pixel dimension when available."""
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def summarize_tag_findings(inspections: Iterable[DicomInspection]) -> Mapping[str, int]:
    """Count DICOM finding codes without grouping by patient or raw tag value."""
    counts: dict[str, int] = {}
    for inspection in inspections:
        for finding in inspection.findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1
    return dict(sorted(counts.items()))

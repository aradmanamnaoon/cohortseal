"""Safe manifest parsing, validation, and serialization."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from cohortseal.errors import ManifestError
from cohortseal.models import CaseRecord, DatasetManifest


def _read_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV or JSON rows. JSON may be a list or an object with ``cases``."""
    try:
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as stream:
                return list(csv.DictReader(stream))
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("cases") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise ManifestError("JSON manifest must be a list or contain a 'cases' list")
            return rows
    except (OSError, json.JSONDecodeError, csv.Error) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    raise ManifestError(f"unsupported manifest format: {path.suffix}; use CSV or JSON")


def load_manifest(path: str | Path, *, dataset_name: str | None = None) -> DatasetManifest:
    """Load a CSV or JSON case manifest without reading image pixels."""
    source = Path(path)
    rows = _read_rows(source)
    try:
        cases = [CaseRecord.model_validate(row) for row in rows]
    except ValidationError as exc:
        raise ManifestError(f"invalid case manifest: {exc}") from exc
    if not cases:
        raise ManifestError("manifest contains no cases")
    counts = Counter(case.case_id for case in cases)
    duplicates = sorted(case_id for case_id, count in counts.items() if count > 1)
    if duplicates:
        raise ManifestError(f"case_id values must be unique; duplicates: {duplicates[:10]}")
    return DatasetManifest(dataset_name=dataset_name or source.stem, cases=cases, source_uri=str(source))


def write_manifest(cases: Iterable[CaseRecord], path: str | Path) -> None:
    """Write cases as deterministic JSON or CSV based on the destination suffix."""
    target = Path(path)
    items = list(cases)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".json":
        target.write_text(json.dumps([item.model_dump(mode="json") for item in items], indent=2) + "\n", encoding="utf-8")
        return
    if target.suffix.lower() != ".csv":
        raise ManifestError("output suffix must be .csv or .json")
    fields = list(CaseRecord.model_fields)
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = item.model_dump(mode="json")
            row["metadata"] = json.dumps(row["metadata"], sort_keys=True)
            writer.writerow(row)


def hash_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Compute a SHA-256 digest in bounded memory, without exposing file contents."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(chunk_size), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ManifestError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()

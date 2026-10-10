"""Read remote dataset manifests from Hugging Face Hub without downloading images."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from cohortseal.errors import CohortSealError
from cohortseal.manifest import load_manifest
from cohortseal.models import DatasetManifest


class HubIntegrationError(CohortSealError):
    """Hugging Face Hub access or manifest validation failure."""


@dataclass(frozen=True, slots=True)
class HubManifest:
    """Validated manifest plus immutable source provenance."""

    repository_id: str
    revision: str
    filename: str
    file_sha256: str
    local_path: Path
    manifest: DatasetManifest


def fetch_manifest(
    repository_id: str,
    filename: str,
    *,
    revision: str = "main",
    token: str | None = None,
    cache_dir: str | Path | None = None,
    dataset_name: str | None = None,
) -> HubManifest:
    """Download exactly one CSV/JSON manifest file and validate it locally.

    The adapter never calls ``snapshot_download`` and does not fetch model code,
    image blobs, or execute repository content. Private Hub tokens are passed only
    to ``hf_hub_download`` and never stored in the returned value.
    """
    if not repository_id.strip() or "/" not in repository_id:
        raise HubIntegrationError("repository_id must use owner/dataset-name form")
    if Path(filename).name != filename or Path(filename).suffix.lower() not in {".csv", ".json"}:
        raise HubIntegrationError("filename must be a single CSV or JSON path component")
    if not revision.strip():
        raise HubIntegrationError("revision must not be blank")
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise HubIntegrationError("install cohortseal[huggingface] to fetch Hub manifests") from exc
    try:
        downloaded = Path(hf_hub_download(
            repo_id=repository_id,
            filename=filename,
            repo_type="dataset",
            revision=revision,
            token=token,
            cache_dir=str(cache_dir) if cache_dir else None,
        ))
    except Exception as exc:
        raise HubIntegrationError(f"could not download Hub manifest '{filename}' from '{repository_id}': {exc}") from exc
    digest = hashlib.sha256()
    try:
        with downloaded.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest = load_manifest(downloaded, dataset_name=dataset_name or repository_id.rsplit("/", 1)[-1])
    except Exception as exc:
        raise HubIntegrationError(f"downloaded file is not a valid CohortSeal manifest: {exc}") from exc
    return HubManifest(repository_id=repository_id, revision=revision, filename=filename,
                       file_sha256=digest.hexdigest(), local_path=downloaded, manifest=manifest)

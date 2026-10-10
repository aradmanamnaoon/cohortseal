# CohortSeal
Patient-level leakage can make medical imaging scores look reliable when they are not.
CohortSeal audits patient and exact-duplicate boundaries, then creates reproducible group splits; its 20,000-patient benchmark keeps group boundaries intact while row-random splitting fails.

## Why this exists

Medical imaging cohorts often contain multiple slices, frames, series, or patches per patient. A row-level random split can put correlated observations on both sides of evaluation. CohortSeal treats the patient group as the unit of assignment, checks declared splits for cross-boundary patient IDs and exact content hashes, and records an immutable report in SQLite.

It is a research engineering tool. A passing audit does not establish clinical validity, external generalizability, de-identification, or absence of near-duplicate images.

## Install and run in five minutes

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[api,dev]'
python examples/create_synthetic_manifest.py
cohortseal audit synthetic_cohort.csv --json --database sqlite:///demo.db
cohortseal split synthetic_cohort.csv split_cohort.csv --seed 42
```

The demo writes fabricated metadata only. A manifest requires `case_id`, `patient_id`, and `path`. Optional columns include `split`, `site`, `label`, `modality`, `study_id`, `series_id`, and `content_sha256`.

See [the expanded quickstart](docs/QUICKSTART.md) for profiling, pipeline checks, reports, and optional adapters.

## Features

- Patient-level split construction with deterministic seed, optional stratification, and site holdout.
- Split audit for patient overlap and exact content-hash duplicates.
- CSV/JSON manifests; image pixel data is not loaded by the core.
- SQLite run history with schema migrations and findings.
- CLI and optional FastAPI interface with audit, split, profile, pipeline, and cohort drift routes.
- Plug-in audit rules through Python entry points.
- Structured JSON logs, in-process metrics hooks, and an experiment lifecycle registry.
- DICOM header risk checks, MONAI datalist export, and a Hugging Face dataset-manifest adapter.
- HTML, JSON, and Markdown reports with subgroup counts and lineage findings.
- Preprocessing fit-scope checks, derived-case lineage validation, and metadata distribution shift summaries.
- Binary classification, patient-cluster bootstrap, and binary segmentation metrics as optional evaluation helpers.

## CLI

```text
cohortseal audit cohort.csv [--dataset-name NAME] [--database URL] [--json]
cohortseal split cohort.csv output.csv [--seed 42] [--holdout-site SITE]
cohortseal show-run RUN_ID [--database URL]
cohortseal profile cohort.csv [--json]
cohortseal pipeline-audit pipeline.json [--json]
cohortseal report cohort.csv report.html [--database URL]
cohortseal dicom-audit /data/header1.dcm /data/header2.dcm [--json]
```

`audit` exits `0` when no error-level finding exists, `2` for audit errors or invalid input, and `4` when a requested run is absent. `--fail-on-warning` changes warnings into a nonzero outcome.

Optional integrations install independently: `pip install -e '.[dicom]'` for pydicom, `pip install -e '.[monai]'` for MONAI transforms, `pip install -e '.[huggingface]'` for Hub manifests, and `pip install -e '.[metrics]'` for NumPy/SciPy metrics. DICOM inspection reads metadata only and does not certify a de-identification profile. Use a stable random secret in `COHORTSEAL_DICOM_TOKEN_KEY` to tokenize patient identifiers locally.

## REST API

Install with `pip install -e '.[api]'`, then run `uvicorn 'cohortseal.api:create_app' --factory`. See [API reference](docs/API.md).

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| POST | `/v1/audits` | Audit and persist submitted metadata |
| GET | `/v1/audits?limit=50` | List summaries |
| GET | `/v1/audits/{run_id}` | Retrieve report and findings |

## Comparison

| Capability | CohortSeal | MONAI / MONAI Label | nnU-Net |
|---|---|---|---|
| Main purpose | Manifest integrity and split auditing | Imaging AI development and interactive annotation/training | Strong segmentation training pipeline |
| Patient-overlap audit | Yes, from manifest IDs | Workflow-specific; not a standalone manifest audit | Split generation is case-key based and configurable |
| Duplicate hash boundary check | Yes, when hashes are supplied | Not its primary purpose | Not its primary purpose |
| Persistent audit ledger | SQLite migrations | Not the central product surface | Split files support reproducibility |
| Clinical validation claim | No | No | No |

This is a focused complement, not a replacement. MONAI and nnU-Net provide substantially broader imaging and training functionality.

## Benchmarks

`benchmarks/compare_splitters.py` compares patient-boundary correctness and runtime for CohortSeal, scikit-learn `GroupShuffleSplit`, and a row-random negative control on 20,000 synthetic patients with four metadata rows each. One run in the development container (Python 3.12.14, five seeds; timings are workload-specific) produced:

| Method | Median split time (s) | Patient groups cross splits? |
|---|---:|---|
| CohortSeal stratified group plan | 0.2247 | No |
| scikit-learn `GroupShuffleSplit` | 0.0211 | No |
| Row-random negative control | 0.0740 | Yes |

This demonstrates the correctness failure of row-random splitting. scikit-learn also preserves groups; CohortSeal adds manifest-level checks, deterministic stratification, optional site holdout, duplicate hash auditing, and persisted audit records around the split operation. It is slower in this microbenchmark and does not claim a runtime advantage. The benchmark is not a clinical validation or image-processing comparison. It does not benchmark nnU-Net because nnU-Net is a segmentation trainer, not an equivalent manifest-audit tool. Re-run the script and record machine, package versions, seed, group count, and cases per patient before comparing results.

## Configuration and examples

Optional YAML keys are shown in [`config.example.yaml`](config.example.yaml). `COHORTSEAL_*` environment variables override file values.

- [Synthetic end-to-end demo](examples/audit_and_split.sh)
- [Custom audit rule](examples/custom_rule.py)
- [REST client](examples/api_client.py)
- [Architecture](docs/ARCHITECTURE.md), [API reference](docs/API.md), [design decision](docs/DESIGN_DECISION.md)

## Privacy and limits

CohortSeal operates on metadata and caller-supplied digests. Findings may contain case IDs and must be handled under the dataset's governance policy. Use pseudonymous IDs and a secured database. Hashes detect exact byte equality only; transformed near duplicates need a separately validated method. The tool does not certify de-identification, assess label quality, inspect preprocessing code, or establish external validity.

## License

MIT. See [LICENSE](LICENSE).

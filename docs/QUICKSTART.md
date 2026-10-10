# Five-minute quickstart

This demo uses fabricated case metadata and creates no medical images.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,api]'
```

## Create a synthetic cohort and audit it

```bash
python examples/create_synthetic_manifest.py
cohortseal audit synthetic_cohort.csv --json --database sqlite:///demo.db
```

The audit assigns a run ID and stores the manifest digest, aggregate counts, and findings in SQLite.

## Create patient-grouped partitions and profile them

```bash
cohortseal split synthetic_cohort.csv split_cohort.csv --seed 42 --stratify label,site
cohortseal profile split_cohort.csv
```

Every record with the same `patient_id` stays in one partition. For a site-held-out experiment, add `--holdout-site site-b`.

## Check preprocessing scope and export a report

```bash
cohortseal pipeline-audit examples/pipeline.json
cohortseal report split_cohort.csv reports/cohort.html --database sqlite:///demo.db
```

The pipeline checker audits declared steps; it cannot inspect arbitrary Python code and should be treated as a contract review.

## Optional adapters

- `pip install -e '.[monai]'` enables MONAI transforms; `examples/export_monai_datalist.py` writes a patient-safe datalist.
- `pip install -e '.[dicom]'` enables DICOM header inspection. Set `COHORTSEAL_DICOM_TOKEN_KEY` to a stable, securely stored random key of at least 16 bytes before using `cohortseal dicom-audit`.
- `pip install -e '.[huggingface]'` enables retrieval of one CSV/JSON manifest by exact filename and revision. Image blobs are not downloaded.
- `pip install -e '.[metrics]'` enables optional NumPy/SciPy segmentation metrics.

# API reference

Start with `pip install -e '.[api]'` and `uvicorn 'cohortseal.api:create_app' --factory`.

## `GET /health`

Returns `{"status":"ok","service":"cohortseal"}`. It is a liveness check, not a database readiness or clinical safety check.

## `POST /v1/audits`

Request:

```json
{"dataset_name":"demo","cases":[{"case_id":"c1","patient_id":"p1","path":"metadata-only/path.nii.gz","split":"train","site":"site-a"}]}
```

Returns HTTP 201 with `run_id`, pass state, counts, and findings. Duplicate `case_id` values and schema errors return HTTP 422. Storage failures return HTTP 503.

## `GET /v1/audits`

Accepts `limit` from 1 through 1000 and returns recent summaries. Invalid bounds return HTTP 422.

## `GET /v1/audits/{run_id}`

Returns stored summary and findings or HTTP 404. Deploy behind an authenticated service boundary before exposing data. Authentication and multi-tenant authorization are not included in this research tool.

## `POST /v1/cohort-profile`

Accepts the same `dataset_name` and `cases` shape as audit. Returns split counts, categorical site/label/modality counts, and coverage findings.

## `POST /v1/splits`

Accepts `cases`, optional `fractions`, `seed`, `stratify_by`, and `holdout_site`. Returns patient-group assignments and their deterministic digest. Invalid constraints return HTTP 422.

## `POST /v1/pipelines/audit`

Accepts `{"steps": [{"name":"split","phase":"split"}, ...]}`. Returns fit-scope, phase-order, and reproducibility findings.

## `POST /v1/cohorts/drift`

Accepts `reference` and `current` case arrays. Returns PSI and Jensen-Shannon divergence for selected metadata categories. These are cohort composition signals, not model performance or clinical drift guarantees.

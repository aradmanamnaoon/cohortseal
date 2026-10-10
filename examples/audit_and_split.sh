#!/usr/bin/env sh
set -eu
python examples/create_synthetic_manifest.py
cohortseal audit synthetic_cohort.csv --json --database sqlite:///demo.db
cohortseal split synthetic_cohort.csv split_cohort.csv --seed 42
echo "Inspect split_cohort.csv; each patient stays in one partition."

"""Create a MONAI datalist from a CohortSeal patient-safe split."""

from pathlib import Path

from cohortseal.manifest import load_manifest
from cohortseal.integrations.monai import patient_group_plan, write_monai_datalist


manifest = load_manifest(Path("synthetic_cohort.csv"))
plan = patient_group_plan(manifest.cases, seed=42, stratify_by=("label", "site"))
output = write_monai_datalist(manifest.cases, "monai_datalist.json", plan=plan)
print(f"Wrote {output}; split digest is {plan.digest}")

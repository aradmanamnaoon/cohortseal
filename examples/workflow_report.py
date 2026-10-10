"""Run all cohort checks and produce an HTML summary with SQLite history."""

from cohortseal.manifest import load_manifest
from cohortseal.storage import RunStore
from cohortseal.workflow import CohortWorkflow


manifest = load_manifest("synthetic_cohort.csv", dataset_name="synthetic-demo")
workflow = CohortWorkflow(store=RunStore("sqlite:///cohortseal-demo.db"))
result = workflow.run(manifest.dataset_name, manifest.cases, report_path="reports/cohort.html")
print(result.summary())

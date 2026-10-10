"""Create a small fabricated manifest for the five-minute CohortSeal demo."""

import csv
from pathlib import Path


output = Path("synthetic_cohort.csv")
with output.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=["case_id", "patient_id", "path", "site", "label"])
    writer.writeheader()
    for patient in range(24):
        for series in range(2):
            writer.writerow({
                "case_id": f"case-{patient:03d}-{series}",
                "patient_id": f"patient-{patient:03d}",
                "path": f"./synthetic/patient-{patient:03d}/series-{series}.nii.gz",
                "site": "site-a" if patient < 12 else "site-b",
                "label": "positive" if patient % 3 == 0 else "negative",
            })
print(f"Wrote fabricated metadata only: {output}")

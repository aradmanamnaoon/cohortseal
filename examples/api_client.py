"""Call a running CohortSeal API with fabricated rows."""

from __future__ import annotations

import json
import urllib.request


payload = {
    "dataset_name": "demo",
    "cases": [
        {"case_id": f"c{i}", "patient_id": f"p{i // 2}", "path": f"demo/{i}.nii.gz", "site": "demo"}
        for i in range(20)
    ],
}
request = urllib.request.Request("http://127.0.0.1:8000/v1/audits",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(request, timeout=10) as response:
    print(response.read().decode())

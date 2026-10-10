"""Minimal custom rule example; register it from a small Python application."""

from collections.abc import Iterable

from cohortseal.models import CaseRecord, Finding, Severity


class MinimumCohortSize:
    """Warn when a cohort is too small for a planned internal split."""

    @property
    def code(self) -> str:
        """Stable rule code used in audit output."""
        return "MINIMUM_PATIENT_GROUPS"

    def run(self, cases: tuple[CaseRecord, ...]) -> Iterable[Finding]:
        """Emit an informational finding when fewer than 30 groups exist."""
        patients = {case.patient_id for case in cases}
        if len(patients) < 30:
            yield Finding(code=self.code, severity=Severity.WARNING,
                          message="Fewer than 30 patient groups; report uncertainty carefully.",
                          evidence={"patient_count": len(patients)})

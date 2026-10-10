"""CohortSeal: auditable patient-aware cohort splitting for medical imaging ML."""

from cohortseal.models import CaseRecord, Finding, SplitAssignment
from cohortseal.audit import AuditEngine, AuditReport
from cohortseal.splitting import SplitPlan, make_group_split

__all__ = ["AuditEngine", "AuditReport", "CaseRecord", "Finding", "SplitAssignment", "SplitPlan", "make_group_split"]
__version__ = "0.1.0"

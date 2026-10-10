"""Entry-point based rule plugin registry."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Iterable

from cohortseal.audit import AuditRule, ExactDuplicateRule, MissingMetadataRule, PatientSplitRule
from cohortseal.errors import PluginError


class RuleRegistry:
    """Manage built-in and third-party audit rules without modifying CohortSeal."""

    def __init__(self) -> None:
        self._rules: dict[str, AuditRule] = {}
        for rule in (PatientSplitRule(), ExactDuplicateRule(), MissingMetadataRule()):
            self.register(rule)

    def register(self, rule: AuditRule, *, replace: bool = False) -> None:
        """Register a rule implementing the ``cohortseal.audit_rules`` protocol."""
        code = getattr(rule, "code", None)
        runner = getattr(rule, "run", None)
        if not isinstance(code, str) or not code.strip() or not callable(runner):
            raise PluginError("rule must expose a non-empty code and callable run(cases)")
        if code in self._rules and not replace:
            raise PluginError(f"audit rule '{code}' is already registered")
        self._rules[code] = rule

    def discover(self) -> tuple[str, ...]:
        """Load installed entry points, isolating import errors with actionable context."""
        loaded: list[str] = []
        try:
            candidates = entry_points(group="cohortseal.audit_rules")
        except TypeError:
            candidates = entry_points().get("cohortseal.audit_rules", ())
        for candidate in candidates:
            try:
                self.register(candidate.load()())
                loaded.append(candidate.name)
            except Exception as exc:
                raise PluginError(f"failed to load plugin '{candidate.name}': {exc}") from exc
        return tuple(loaded)

    def all(self) -> tuple[AuditRule, ...]:
        """Return rules in deterministic code order."""
        return tuple(self._rules[key] for key in sorted(self._rules))


class RequireLabelPlugin:
    """Example extension that enforces non-empty labels for supervised cohorts."""

    @property
    def code(self) -> str:
        """Stable finding code."""
        return "LABEL_REQUIRED"

    def run(self, cases: tuple) -> Iterable:
        """Yield one error finding per case without a label."""
        from cohortseal.models import Finding, Severity

        for case in cases:
            if not case.label:
                yield Finding(code=self.code, severity=Severity.ERROR,
                              message="Case has no supervised label.", case_ids=(case.case_id,))


class RequireSitePlugin:
    """Example extension that fails when site metadata is absent."""

    @property
    def code(self) -> str:
        """Stable finding code."""
        return "SITE_REQUIRED"

    def run(self, cases: tuple) -> Iterable:
        """Yield an error summarizing records without site attribution."""
        from cohortseal.models import Finding, Severity

        missing = tuple(case.case_id for case in cases if not case.site)
        if missing:
            yield Finding(code=self.code, severity=Severity.ERROR,
                          message=f"Site is missing for {len(missing)} cases.", case_ids=missing)

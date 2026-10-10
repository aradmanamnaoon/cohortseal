"""Safe machine-readable and human-readable cohort audit reports."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cohortseal.audit import AuditReport
from cohortseal.profile import SplitProfile


@dataclass(frozen=True, slots=True)
class ReportArtifact:
    """Details for one report written to disk."""

    path: Path
    format: str
    byte_count: int


class ReportBuilder:
    """Render audit and cohort profiles without embedding image or raw patient data."""

    def __init__(self, *, title: str = "CohortSeal cohort report", generated_at: datetime | None = None) -> None:
        self.title = title.strip() or "CohortSeal cohort report"
        self.generated_at = generated_at or datetime.now(timezone.utc)
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must include a timezone")

    def build_payload(self, audit: AuditReport | None, profile: SplitProfile | None,
                      *, dataset_name: str, manifest_digest: str | None = None) -> dict[str, Any]:
        """Construct deterministic report data with only aggregate cohort counts."""
        return {
            "schema_version": "1",
            "title": self.title,
            "dataset_name": dataset_name,
            "generated_at": self.generated_at.isoformat(),
            "manifest_digest": manifest_digest,
            "audit": {
                "passed": audit.passed,
                "case_count": audit.case_count,
                "patient_count": audit.patient_count,
                "rule_count": audit.rule_count,
                "summary": audit.summary(),
                "findings": [finding.model_dump(mode="json") for finding in audit.findings],
            } if audit else None,
            "profile": profile.to_dict() if profile else None,
        }

    def render_json(self, payload: dict[str, Any]) -> str:
        """Serialize report payload as stable UTF-8 JSON."""
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def render_markdown(self, payload: dict[str, Any]) -> str:
        """Render a compact Markdown report suitable for code review artifacts."""
        lines = [f"# {payload['title']}", "", f"Dataset: `{payload['dataset_name']}`",
                 f"Generated: `{payload['generated_at']}`"]
        if payload.get("manifest_digest"):
            lines.append(f"Manifest SHA-256: `{payload['manifest_digest']}`")
        audit = payload.get("audit")
        if audit:
            passed = payload.get("overall_passed", audit["passed"])
            lines.extend(["", "## Audit", "", f"Status: **{'PASS' if passed else 'FAIL'}**",
                          f"Cases: {audit['case_count']}", f"Patient groups: {audit['patient_count']}",
                          f"Rules: {audit['rule_count']}"])
            report_findings = payload.get("all_findings", audit["findings"])
            if report_findings:
                lines.extend(["", "### Findings", "", "| Severity | Rule | Message |", "|---|---|---|"])
                for item in report_findings:
                    message = str(item["message"]).replace("|", "\\|").replace("\n", " ")
                    lines.append(f"| {item['severity']} | `{item['code']}` | {message} |")
            else:
                lines.extend(["", "No findings were emitted."])
        profile = payload.get("profile")
        if profile:
            lines.extend(["", "## Cohort profile", "", f"Cases: {profile['total_cases']}",
                          f"Patient groups: {profile['total_patients']}"])
            if profile["split_counts"]:
                lines.extend(["", "| Split | Cases | Patients |", "|---|---:|---:|"])
                for split, values in sorted(profile["split_counts"].items()):
                    lines.append(f"| {split} | {values['cases']} | {values['patients']} |")
            if profile["categories"]:
                lines.extend(["", "### Category counts", "", "| Field | Value | Cases | Patients |", "|---|---|---:|---:|"])
                for category in profile["categories"]:
                    value = str(category["value"]).replace("|", "\\|")
                    lines.append(f"| {category['field']} | {value} | {category['cases']} | {category['patients']} |")
        return "\n".join(lines) + "\n"

    def render_html(self, payload: dict[str, Any]) -> str:
        """Render a standalone HTML report with embedded SVG cohort charts."""
        title = html.escape(str(payload["title"]))
        dataset = html.escape(str(payload["dataset_name"]))
        generated = html.escape(str(payload["generated_at"]))
        audit = payload.get("audit") or {}
        profile = payload.get("profile") or {}
        status = "PASS" if payload.get("overall_passed", audit.get("passed", True)) else "FAIL"
        status_class = "pass" if status == "PASS" else "fail"
        split_counts = profile.get("split_counts", {})
        chart = self._svg_bar_chart({name: value.get("patients", 0) for name, value in split_counts.items()})
        findings_html = self._findings_table(payload.get("all_findings", audit.get("findings", [])))
        category_html = self._category_table(profile.get("categories", []))
        digest = payload.get("manifest_digest")
        digest_html = f"<p class='muted'>Manifest digest: <code>{html.escape(str(digest))}</code></p>" if digest else ""
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#10151d;--panel:#18212c;--line:#2b3745;--text:#edf2f7;--muted:#aab6c4;--accent:#56d3b0;--error:#ff7373}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,sans-serif}}
main{{max-width:1000px;margin:32px auto;padding:0 18px}}h1{{font-size:30px;margin-bottom:4px}}h2{{font-size:19px;margin:0 0 14px}}
.muted{{color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:22px 0}}
.card,section{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}}
.value{{font-size:26px;font-weight:700}}.pass{{color:var(--accent)}}.fail{{color:var(--error)}}section{{margin:14px 0;overflow:auto}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:9px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:600}}code{{overflow-wrap:anywhere}}svg{{width:100%;height:auto;max-height:260px}}
@media(max-width:600px){{main{{margin:18px auto}}h1{{font-size:24px}}}}
</style></head><body><main>
<h1>{title}</h1><p class="muted">Dataset: {dataset} · Generated: {generated}</p>{digest_html}
<div class="grid"><div class="card"><div class="muted">Audit status</div><div class="value {status_class}">{status}</div></div>
<div class="card"><div class="muted">Cases</div><div class="value">{int(audit.get('case_count', profile.get('total_cases', 0)))}</div></div>
<div class="card"><div class="muted">Patient groups</div><div class="value">{int(audit.get('patient_count', profile.get('total_patients', 0)))}</div></div>
<div class="card"><div class="muted">Findings</div><div class="value">{len(payload.get('all_findings', audit.get('findings', [])))}</div></div></div>
<section><h2>Patient groups by split</h2>{chart}</section>
<section><h2>Audit findings</h2>{findings_html}</section>
<section><h2>Cohort composition</h2>{category_html}</section>
<p class="muted">CohortSeal reports metadata integrity checks. This report does not establish clinical validity or de-identification compliance.</p>
</main></body></html>'''

    def write(self, content: str, path: str | Path, *, format_name: str) -> ReportArtifact:
        """Write report content atomically to a destination file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(target)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        return ReportArtifact(path=target, format=format_name, byte_count=target.stat().st_size)

    def _svg_bar_chart(self, values: dict[str, int]) -> str:
        """Build a small accessible SVG bar chart from split patient counts."""
        if not values:
            return "<p class='muted'>No split assignments are available.</p>"
        names = sorted(values)
        max_value = max(values.values()) or 1
        width, height, bar_height, gap = 720, 65 + len(names) * 46, 24, 18
        parts = [f'<svg role="img" aria-label="Patient groups by split" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
        for index, name in enumerate(names):
            y = 30 + index * (bar_height + gap)
            bar_width = int(440 * values[name] / max_value)
            safe_name = html.escape(name)
            parts.append(f'<text x="8" y="{y+18}" fill="#edf2f7" font-size="14">{safe_name}</text>')
            parts.append(f'<rect x="150" y="{y}" width="{bar_width}" height="{bar_height}" rx="5" fill="#56d3b0"/>')
            parts.append(f'<text x="{160+bar_width}" y="{y+18}" fill="#edf2f7" font-size="14">{values[name]}</text>')
        parts.append("</svg>")
        return "".join(parts)

    @staticmethod
    def _findings_table(findings: list[dict[str, Any]]) -> str:
        """Render escaped findings table or an empty state."""
        if not findings:
            return "<p class='pass'>No audit findings.</p>"
        rows = []
        for item in findings:
            rows.append("<tr><td>" + html.escape(str(item.get("severity", ""))) + "</td><td><code>" +
                        html.escape(str(item.get("code", ""))) + "</code></td><td>" +
                        html.escape(str(item.get("message", ""))) + "</td></tr>")
        return "<table><thead><tr><th>Severity</th><th>Rule</th><th>Message</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"

    @staticmethod
    def _category_table(categories: list[dict[str, Any]]) -> str:
        """Render escaped category counts or an empty state."""
        if not categories:
            return "<p class='muted'>No category metadata is available.</p>"
        rows = []
        for item in categories:
            rows.append("<tr><td>" + html.escape(str(item.get("field", ""))) + "</td><td>" +
                        html.escape(str(item.get("value", ""))) + "</td><td>" +
                        str(int(item.get("cases", 0))) + "</td><td>" +
                        str(int(item.get("patients", 0))) + "</td></tr>")
        return "<table><thead><tr><th>Field</th><th>Value</th><th>Cases</th><th>Patients</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"

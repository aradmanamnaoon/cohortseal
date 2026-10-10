"""Command line interface for audits, split generation, and run inspection."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from cohortseal.audit import AuditEngine
from cohortseal.config import load_settings
from cohortseal.errors import CohortSealError
from cohortseal.manifest import load_manifest, write_manifest
from cohortseal.observability import configure_logging
from cohortseal.plugins import RuleRegistry
from cohortseal.profile import CohortProfiler
from cohortseal.provenance import validate_pipeline_dict
from cohortseal.splitting import make_group_split
from cohortseal.storage import RunStore
from cohortseal.workflow import CohortWorkflow


def build_parser() -> argparse.ArgumentParser:
    """Create parser with complete command help."""
    parser = argparse.ArgumentParser(prog="cohortseal", description="Audit medical imaging cohorts before training.")
    parser.add_argument("--config", help="Optional YAML configuration file")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Audit a manifest for split and duplicate leakage")
    audit.add_argument("manifest", type=Path)
    audit.add_argument("--dataset-name")
    audit.add_argument("--database", help="Override SQLite database URL")
    audit.add_argument("--json", action="store_true", help="Emit JSON report")
    audit.add_argument("--fail-on-warning", action="store_true")
    split = commands.add_parser("split", help="Create patient-grouped deterministic splits")
    split.add_argument("manifest", type=Path)
    split.add_argument("output", type=Path)
    split.add_argument("--seed", type=int, default=42)
    split.add_argument("--holdout-site")
    split.add_argument("--stratify", default="label", help="Comma-separated fields: label,site,modality")
    inspect = commands.add_parser("show-run", help="Print a previously stored audit run")
    inspect.add_argument("run_id")
    inspect.add_argument("--database")
    profile = commands.add_parser("profile", help="Summarize cohort strata and split coverage")
    profile.add_argument("manifest", type=Path)
    profile.add_argument("--json", action="store_true")
    pipeline = commands.add_parser("pipeline-audit", help="Check preprocessing order for common leakage")
    pipeline.add_argument("pipeline", type=Path)
    pipeline.add_argument("--json", action="store_true")
    report = commands.add_parser("report", help="Run cohort checks and write JSON, Markdown, or HTML report")
    report.add_argument("manifest", type=Path)
    report.add_argument("output", type=Path)
    report.add_argument("--dataset-name")
    report.add_argument("--database")
    dicom = commands.add_parser("dicom-audit", help="Inspect DICOM headers without decoding pixels")
    dicom.add_argument("paths", nargs="+", type=Path)
    dicom.add_argument("--token-key-env", default="COHORTSEAL_DICOM_TOKEN_KEY",
                       help="Environment variable containing a stable random secret of at least 16 bytes")
    dicom.add_argument("--json", action="store_true")
    return parser


def _audit(args: argparse.Namespace, settings) -> int:
    """Execute audit and persist the immutable result."""
    manifest = load_manifest(args.manifest, dataset_name=args.dataset_name)
    registry = RuleRegistry()
    registry.discover()
    report = AuditEngine(registry.all()).run(manifest.cases)
    run_id = str(uuid.uuid4())
    digest_payload = json.dumps([case.model_dump(mode="json") for case in manifest.cases], sort_keys=True)
    import hashlib
    digest = hashlib.sha256(digest_payload.encode()).hexdigest()
    database = args.database or settings.database_url
    RunStore(database).save_run(run_id, manifest.dataset_name, digest, report.passed,
                               report.case_count, report.patient_count, report.summary(), report.findings)
    payload = {"run_id": run_id, "dataset": manifest.dataset_name,
               **report.summary(), "findings": [item.model_dump(mode="json") for item in report.findings]}
    print(json.dumps(payload, indent=2) if args.json else _format_report(payload))
    fail_warning = args.fail_on_warning or settings.audit_fail_on_warning
    has_warning = any(item.severity.value == "warning" for item in report.findings)
    return 0 if report.passed and not (fail_warning and has_warning) else 2


def _format_report(payload: dict) -> str:
    """Render a terminal-readable audit summary."""
    status = "PASS" if payload["passed"] else "FAIL"
    lines = [f"{status}  {payload['dataset']}  ({payload['cases']} cases, {payload['patients']} patients)",
             f"Run ID: {payload['run_id']}"]
    lines.extend(f"[{item['severity'].upper()}] {item['code']}: {item['message']}" for item in payload["findings"])
    return "\n".join(lines)


def _format_findings(findings) -> str:
    """Render generic findings for pipeline and metadata checks."""
    if not findings:
        return "PASS  no findings"
    return "\n".join(f"[{item.severity.value.upper()}] {item.code}: {item.message}" for item in findings)


def _format_profile(profile) -> str:
    """Render cohort counts without listing patient identifiers."""
    lines = [f"Cases: {profile.total_cases}", f"Patient groups: {profile.total_patients}"]
    for split, values in profile.split_counts.items():
        lines.append(f"{split}: {values['cases']} cases, {values['patients']} patients")
    lines.extend(_format_findings(profile.findings).splitlines())
    return "\n".join(lines)


def _format_dicom_report(payload: dict) -> str:
    """Render finding codes and redacted DICOM metadata only."""
    files = payload["files"]
    lines = [f"Files: {len(files)}", f"Findings: {payload['findings']}"]
    for file_result in files:
        for finding in file_result["findings"]:
            lines.append(f"[{finding['severity'].upper()}] {finding['code']}: {finding['message']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        configure_logging(settings.log_level, json_output=settings.log_json)
        if args.command == "audit":
            return _audit(args, settings)
        if args.command == "split":
            manifest = load_manifest(args.manifest)
            plan = make_group_split(manifest.cases, seed=args.seed,
                                    stratify_by=tuple(item for item in args.stratify.split(",") if item),
                                    holdout_site=args.holdout_site)
            write_manifest(plan.apply(manifest.cases), args.output)
            print(json.dumps({"digest": plan.digest, "patients": len(plan.assignments),
                              "splits": {name: sum(x.split == name for x in plan.assignments)
                                         for name in sorted({x.split for x in plan.assignments})}}, indent=2))
            return 0
        if args.command == "show-run":
            run = RunStore(args.database or settings.database_url).get_run(args.run_id)
            if run is None:
                print(f"run not found: {args.run_id}", file=sys.stderr)
                return 4
            print(json.dumps(run, indent=2))
            return 0
        if args.command == "profile":
            manifest = load_manifest(args.manifest)
            result = CohortProfiler().profile(manifest.cases)
            print(json.dumps(result.to_dict(), indent=2) if args.json else _format_profile(result))
            return 2 if any(item.severity.value == "error" for item in result.findings) else 0
        if args.command == "pipeline-audit":
            payload = json.loads(args.pipeline.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("pipeline JSON must be an array of step objects")
            result = validate_pipeline_dict(payload)
            print(json.dumps(result.to_dict(), indent=2) if args.json else _format_findings(result.findings))
            return 0 if result.passed else 2
        if args.command == "report":
            manifest = load_manifest(args.manifest, dataset_name=args.dataset_name)
            store = RunStore(args.database) if args.database else None
            result = CohortWorkflow(store=store).run(manifest.dataset_name, manifest.cases,
                                                     report_path=str(args.output))
            report_path = result.report_artifact.path if result.report_artifact else args.output
            print(json.dumps({**result.summary(), "report_path": str(report_path)}, indent=2))
            return 0 if result.passed else 2
        if args.command == "dicom-audit":
            from cohortseal.integrations.dicom import DicomInspector
            secret = os.environ.get(args.token_key_env)
            if not secret:
                raise ValueError(f"set {args.token_key_env} to a stable random secret before DICOM audit")
            batch = DicomInspector(token_key=secret.encode("utf-8")).inspect_many(args.paths)
            result = {**batch.summary(), "files": [item.to_dict() for item in batch.files]}
            print(json.dumps(result, indent=2) if args.json else _format_dicom_report(result))
            return 0 if batch.passed else 2
        return 1
    except (CohortSealError, ValueError) as exc:
        print(f"cohortseal: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

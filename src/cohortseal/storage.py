"""SQLite run registry with versioned migrations and explicit transactions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cohortseal.errors import StorageError
from cohortseal.models import Finding


MIGRATIONS: tuple[str, ...] = (
    """CREATE TABLE audit_runs (
        run_id TEXT PRIMARY KEY,
        dataset_name TEXT NOT NULL,
        manifest_digest TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
        case_count INTEGER NOT NULL CHECK (case_count >= 0),
        patient_count INTEGER NOT NULL CHECK (patient_count >= 0),
        summary_json TEXT NOT NULL
    )""",
    """CREATE TABLE findings (
        finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES audit_runs(run_id) ON DELETE CASCADE,
        code TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        case_ids_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL
    )""",
    "CREATE INDEX findings_run_idx ON findings(run_id, severity, code)",
    """CREATE TABLE experiments (
        experiment_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('created','running','completed','failed','archived')),
        dataset_digest TEXT NOT NULL,
        split_digest TEXT NOT NULL,
        pipeline_digest TEXT,
        model_family TEXT NOT NULL,
        config_json TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX experiments_status_idx ON experiments(status, created_at)",
    """CREATE TABLE experiment_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
        from_status TEXT,
        to_status TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
)


class RunStore:
    """Persist audit metadata and findings in SQLite; never store imaging pixels."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        if self.database.startswith("sqlite:///"):
            self.database = self.database.removeprefix("sqlite:///")
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise StorageError(f"SQLite operation failed: {exc}") from exc
        finally:
            connection.close()

    def _initialize(self) -> None:
        """Apply unapplied schema migrations atomically."""
        try:
            with self._connect() as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
                current = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
                for version, statement in enumerate(MIGRATIONS, start=1):
                    if version > current:
                        connection.execute(statement)
                        connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
        except sqlite3.Error as exc:
            raise StorageError(f"cannot initialize database: {exc}") from exc

    def save_run(self, run_id: str, dataset_name: str, manifest_digest: str,
                 passed: bool, case_count: int, patient_count: int,
                 summary: dict, findings: tuple[Finding, ...]) -> None:
        """Insert one run and all associated findings as one transaction."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO audit_runs(run_id,dataset_name,manifest_digest,passed,case_count,patient_count,summary_json) VALUES(?,?,?,?,?,?,?)",
                (run_id, dataset_name, manifest_digest, int(passed), case_count, patient_count,
                 json.dumps(summary, sort_keys=True)),
            )
            connection.executemany(
                "INSERT INTO findings(run_id,code,severity,message,case_ids_json,evidence_json) VALUES(?,?,?,?,?,?)",
                [(run_id, f.code, f.severity.value, f.message, json.dumps(f.case_ids),
                  json.dumps(f.evidence, sort_keys=True)) for f in findings],
            )

    def get_run(self, run_id: str) -> dict | None:
        """Return one run with findings, or ``None`` when not found."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM audit_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["summary"] = json.loads(result.pop("summary_json"))
            result["findings"] = [
                {**dict(item), "case_ids": json.loads(item["case_ids_json"]),
                 "evidence": json.loads(item["evidence_json"])}
                for item in connection.execute("SELECT * FROM findings WHERE run_id=? ORDER BY finding_id", (run_id,))
            ]
            return result

    def list_runs(self, limit: int = 50) -> list[dict]:
        """List recent run summaries without expanded finding records."""
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT run_id,dataset_name,manifest_digest,created_at,passed,case_count,patient_count,summary_json FROM audit_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )]

    def create_experiment(self, experiment_id: str, name: str, dataset_digest: str,
                          split_digest: str, pipeline_digest: str | None,
                          model_family: str, config: dict, tags: list[str]) -> None:
        """Create an experiment and initial lifecycle event atomically."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO experiments(experiment_id,name,status,dataset_digest,split_digest,pipeline_digest,model_family,config_json,tags_json) VALUES(?,?,'created',?,?,?,?,?,?)",
                (experiment_id, name, dataset_digest, split_digest, pipeline_digest,
                 model_family, json.dumps(config, sort_keys=True), json.dumps(tags)),
            )
            connection.execute(
                "INSERT INTO experiment_events(experiment_id,from_status,to_status,note) VALUES(?,NULL,'created','experiment registered')",
                (experiment_id,),
            )

    def get_experiment(self, experiment_id: str) -> dict | None:
        """Return an experiment with its ordered status history."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["config"] = json.loads(result.pop("config_json"))
            result["tags"] = json.loads(result.pop("tags_json"))
            result["events"] = [dict(event) for event in connection.execute(
                "SELECT from_status,to_status,note,created_at FROM experiment_events WHERE experiment_id=? ORDER BY event_id",
                (experiment_id,),
            )]
            return result

    def list_experiments(self, limit: int = 50, *, status: str | None = None) -> list[dict]:
        """List experiment summaries with optional lifecycle filter."""
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        query = "SELECT experiment_id,name,status,dataset_digest,split_digest,pipeline_digest,model_family,created_at,updated_at FROM experiments"
        parameters: tuple[object, ...] = ()
        if status:
            query += " WHERE status=?"
            parameters = (status,)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters += (limit,)
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, parameters)]

    def transition_experiment(self, experiment_id: str, expected_status: str,
                              next_status: str, note: str | None = None) -> bool:
        """Atomically transition status only when the current status matches expectation."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE experiments SET status=?,updated_at=CURRENT_TIMESTAMP WHERE experiment_id=? AND status=?",
                (next_status, experiment_id, expected_status),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "INSERT INTO experiment_events(experiment_id,from_status,to_status,note) VALUES(?,?,?,?)",
                (experiment_id, expected_status, next_status, note),
            )
            return True

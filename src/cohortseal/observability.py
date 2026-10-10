"""Structured logging and lightweight instrumentation hooks."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from contextlib import contextmanager
from typing import Iterator


class JsonFormatter(logging.Formatter):
    """Format log records as structured JSON without serializing arbitrary objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Render timestamp, severity, logger, message, and safe scalar context."""
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("run_id", "dataset_name", "rule_code", "duration_ms", "case_count", "patient_count", "finding_count", "passed"):
            value = getattr(record, key, None)
            if isinstance(value, (str, int, float, bool)):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure package logging once per process."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if json_output else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("cohortseal")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False


class Metrics:
    """In-process counters and duration aggregates, replaceable by a metrics backend."""

    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._durations: dict[str, list[float]] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a named non-negative counter."""
        if amount < 0:
            raise ValueError("metric increment must be non-negative")
        self._counters[name] += amount

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        """Record wall time in milliseconds for an operation."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self._durations.setdefault(name, []).append((time.perf_counter() - started) * 1000)

    def snapshot(self) -> dict[str, object]:
        """Return a stable metrics snapshot suitable for logs or /metrics adapters."""
        return {
            "counters": dict(sorted(self._counters.items())),
            "durations_ms": {
                key: {"count": len(values), "mean": sum(values) / len(values), "max": max(values)}
                for key, values in sorted(self._durations.items()) if values
            },
        }

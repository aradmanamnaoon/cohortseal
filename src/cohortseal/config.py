"""File, environment, and explicit configuration loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cohortseal.errors import ConfigurationError


class Settings(BaseModel):
    """Runtime settings, with environment variables taking precedence over YAML."""

    model_config = ConfigDict(extra="forbid")

    database_url: str = "sqlite:///cohortseal.db"
    log_level: str = "INFO"
    log_json: bool = True
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    audit_fail_on_warning: bool = False


def load_settings(path: str | Path | None = None, *, environ: dict[str, str] | None = None) -> Settings:
    """Load optional YAML and COHORTSEAL_* environment values."""
    values: dict[str, Any] = {}
    if path:
        try:
            parsed = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigurationError(f"cannot load config {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ConfigurationError("configuration file must contain a mapping")
        values.update(parsed)
    env = os.environ if environ is None else environ
    mapping = {
        "DATABASE_URL": "database_url", "LOG_LEVEL": "log_level", "LOG_JSON": "log_json",
        "API_HOST": "api_host", "API_PORT": "api_port", "AUDIT_FAIL_ON_WARNING": "audit_fail_on_warning",
    }
    for suffix, key in mapping.items():
        name = f"COHORTSEAL_{suffix}"
        if name in env:
            values[key] = env[name]
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        raise ConfigurationError(str(exc)) from exc

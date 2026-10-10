"""Configuration precedence and plugin contract checks."""

import pytest

from cohortseal.config import load_settings
from cohortseal.errors import PluginError
from cohortseal.plugins import RequireLabelPlugin, RuleRegistry


def test_environment_overrides_yaml(tmp_path):
    """Environment values take precedence over file settings."""
    config = tmp_path / "config.yaml"
    config.write_text("api_port: 9001\nlog_level: DEBUG\n")
    settings = load_settings(config, environ={"COHORTSEAL_API_PORT": "9002"})
    assert settings.api_port == 9002
    assert settings.log_level == "DEBUG"


def test_registry_loads_builtin_and_custom_rules():
    """Built-in rules coexist with custom behavior without forking."""
    registry = RuleRegistry()
    registry.register(RequireLabelPlugin())
    assert "LABEL_REQUIRED" in {rule.code for rule in registry.all()}


def test_registry_rejects_duplicate_and_invalid_plugins():
    """Ambiguous or nonconforming plugins cannot silently replace rules."""
    registry = RuleRegistry()
    with pytest.raises(PluginError):
        registry.register(RequireLabelPlugin())
    with pytest.raises(PluginError):
        registry.register(object())

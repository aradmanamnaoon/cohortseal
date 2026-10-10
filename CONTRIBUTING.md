# Contributing

1. Create a virtual environment and run `pip install -e '.[api,dev]'`.
2. Run `ruff check src tests examples`, `mypy src/cohortseal`, and `pytest`.
3. Add tests for new rules, split constraints, and persistence behavior.
4. Keep logs free of raw patient identifiers and never add real medical data to fixtures.
5. Document limitations and do not describe an integrity check as clinical validation.

For a new rule, implement `code` and `run(cases)` and register it with the `cohortseal.audit_rules` entry-point group. See [custom_rule.py](examples/custom_rule.py).

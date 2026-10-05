# Incremental verification

Before regeneration:

- Existing `test_live.py::test_wire_schema_and_extra_fields`: failed exact model/schema parity.
- New populated waiting-facts test: failed because task_revision/task_intent_sha256 were unexpected
  under the published `additionalProperties=false` TaskView contract.

After regeneration:

```sh
.venv/bin/pytest -q tests/team_view/test_snapshot_schema.py tests/team_view/test_live.py::test_wire_schema_and_extra_fields
# 14 passed in 0.65 seconds
.venv/bin/ruff check tests/team_view/test_snapshot_schema.py
# All checks passed
.venv/bin/ruff format --check tests/team_view/test_snapshot_schema.py
# checked after formatting the new test
.venv/bin/mypy src/ai_software_engineer/team_view/models.py tests/team_view/test_snapshot_schema.py
# Success: no issues found in 2 source files
git diff --check
# passed
```

The model path is supplied to mypy to resolve the local source tree; models are unchanged. No
MySQL, provider or full-suite tests were run. Root performs independent review and release.

Independent checker verified complete parity, the pure additive diff, nested extra-field rejection,
legacy absence/null compatibility and all 14 targeted tests. No remaining finding. Root's same
targeted selection also passed. Published runtime models and durable records are unchanged.

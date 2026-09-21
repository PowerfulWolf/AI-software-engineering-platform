# Verification

## Automated checks

- `pytest -q tests/web_console/test_manager.py tests/web_console/test_knowledge_resolution.py tests/team_view/test_live.py::test_wire_schema_and_extra_fields tests/manager/test_joint_designer_feedback.py tests/knowledge/test_stages.py tests/contracts/test_json_schema_contracts.py` — 106 passed.
- `node --check src/ai_software_engineer/team_view/app.js` — passed.
- `node --test tests/team_view/ui.test.cjs` — 6 passed.
- `.venv/bin/ruff check` on all changed Python files — passed.
- `.venv/bin/mypy` on all changed Python files — passed.
- `git diff --check` — passed.

The browser interaction suite was not run because this checkout does not have its optional
`playwright` dependency installed; the dependency-free UI contract suite and JavaScript syntax
check passed.

## Durable recovery

The existing Requirement remains the source of truth. After the code commit, the local Console will
receive one exact `RECOVER_DESIGN` operation bound to the checkpoint SHA shown by the live snapshot.
The operation ID, result, successor checkpoint and model-call diagnostics will be recorded here only
after the service has durably completed; no sidecar or database row is edited directly.

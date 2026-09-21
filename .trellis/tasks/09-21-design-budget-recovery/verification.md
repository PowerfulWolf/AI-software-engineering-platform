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

The existing Requirement remains the source of truth. The local Console received the following
formal Operations; no sidecar or database row was edited directly:

- `operation_a727231d8f17d3af1fbb39f4a171fd1d` — `RECOVER_DESIGN`, exact input checkpoint
  `22f87450416d9202ce2592eabe71e8259ab37e014f101e4c647e3b645daae693`. It preserved the failed
  Operation record and appended the recovery checkpoint; the first execution then failed before a
  provider call because the manually started Console lacked the configured runtime environment.
- `operation_ffd70daf7a63492dc32478780d47bcc0` — `CONTINUE_DELIVERY`, exact successor checkpoint
  `b73fc4ddd1ec9e6ad726fead30928b63582108565503da56ee5b667351299128`. After restarting the
  Console with the existing `runtime.env`, the Designer knowledge route made two real calls; both
  provider routes returned HTTP 504 `PROVIDER_UNAVAILABLE`. The Operation is durably `FAILED` with
  that safe error, and the Requirement remains `DESIGNING` at checkpoint
  `c898a45c3a8ea95321909c990b4830d78826d25e798cf39ece6f75cb4c465834`, attempts `design=2`.

The approved ProductSpec, approval, dialogue, all earlier knowledge waits/resolutions, both failed
Operations and every checkpoint remain available. The provider 504 is an external route failure;
no further attempt was spent after the recorded failure.

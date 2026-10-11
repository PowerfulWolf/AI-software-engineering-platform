# Implementation and verification

## Allowed changes and resulting behavior

Child-owned backend paths are `domain/{execution_baseline,delivery_resolution}.py`,
`manager/{stopped_provider_checkpoint,completed_output_checkpoint,baseline_models,
baseline_production,baseline_store,execution_baseline,delivery_wait}.py`, the exact
confirmation forwarding in `production_host.py`, `work_queue/baseline.py`,
`team_view/engineering_history.py`, related incremental tests, schema synchronization
and generated contracts, and this task/core spec documentation. Root independently
owns Console JS/manifest/action copy, real browser tests, public MySQL composition
fixtures and rollout. Shared checkout edits were preserved.

- Added exact stopped-provider proof and purpose, initial allowlist AUTH only.
  Genuine native stop is failed/nonzero/no-output with no interruption cause and
  optional matching original AUTH code; historical absent code remains compatible.
- Same-base preparation preserves existing legal draft/HEAD/branch. Original
  failure, immutable claim/stop and full inventory are verified under real Task
  lock/idle SQL fence. A permanent failure cannot introduce new noncache writes.
- Source update uses the existing different-target/native-rule/conflict gates and
  the same proof. Final SQL callback separately verifies old stop/claim and the new
  workspace, avoiding an invalid comparison against the old baseline inventory.
- Exact human prerequisite confirmation always saves PAUSE, followed by existing
  latest-bound explicit RESUME. One ordinary frozen work reservation is consumed,
  no transient refund or original result rewrite; exact replay is idempotent.
- Read-only INSPECT exports optional exact AUTH hint with no permitted resolution.
  Timeline says prerequisite declaration/preserved draft/pause rather than claiming
  a same-base source update or model execution. Required Context remains truthful.
- Generated/published schema guards cover permanent failure, mixed-proof refusal,
  human PAUSE and all embedded bindings; old engineering guards remain canonical.
  Fresh regeneration removes the new proof output first and requires deterministic
  regeneration. Three ordering-only schemas were restored only after parsed JSON
  equality with HEAD, avoiding unrelated generated diffs.

## Incremental verification

All Python commands use `PYTHONPATH=src`, and mypy also uses `MYPYPATH=src`, because
the shared venv editable installation points at another checkout:

```text
/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python
```

- Initial red: the first new provider-retry tests failed importing the absent new
  proof module. Implementation followed the typed contract.
- First checkpoint/service/completed regression: **78 passed in109.77s**.
- New proof/service/fresh SQL/source/claim/mutation/schema/regen/pause matrix:
  **63 passed in95.52s**. This includes fresh SQL callback acceptance and rejection
  for both same-base and source update after claim/inventory drift.
- Exact real AUTH code, legacy absent-code and new read-only timeline checks:
  targeted **2 passed**; existing engineering history **36 passed in40.60s**.
- Scoped Ruff check: passed across all child-owned changed Python sources, tests
  and generator. Strict mypy: **11 changed source files passed**, external cache
  `/tmp/ase-stopped-provider-retry-mypy`.
- Independent read-only reviewer: no blocking findings; independently selected
  backend **22 passed**, fresh/embedded schema **10 passed**, real AUTH-code/absent
  compatibility/proof negative checks **2 passed**. No production/model operations.
- Root separately reported the two public MySQL/fake-native full Coder→QA→Review
  paths passed; final real AUTH-code fixture retest is recorded by Root separately.
- Final combined affected proof/rescue/baseline/wait/schema regression:
  **190 passed in335.02s**. Exact AUTH-code/timeline tests added during this run
  were separately verified above. Fresh regeneration with the new standalone
  proof removed before generation: **2 passed in4.60s**. No full suite was run.

```sh
PYTHONPATH=src <python> -m pytest \
  tests/manager/test_stopped_provider_retry.py \
  tests/manager/test_completed_output_rescue.py \
  tests/manager/test_completed_output_checkpoint.py \
  tests/manager/test_execution_baseline.py \
  tests/manager/test_delivery_wait.py \
  tests/contracts/test_stopped_provider_retry_schema.py \
  tests/contracts/test_repair_schema_generation.py \
  tests/contracts/test_baseline_pause_schema.py -q --tb=short
PYTHONPATH=src <python> -m pytest tests/team_view/test_engineering_history.py -q
PYTHONPATH=src <python> -m pytest \
  tests/contracts/test_stopped_provider_retry_schema.py::test_every_embedded_binding_requires_human_pause_and_exact_provider_proof -q
```

The focused command covers only affected proof, baseline, wait, history and schema
contracts. Cross-layer verification traced exact proposal/execute confirmation from
Console intent through Host, authorization, immutable Binding, fenced consumption
and separate resume; historical canonical optional fields remain excluded.

## 存量数据处置, risk and rollback

No schema migration or direct database repair. No historical Task, outcome,
approval, accepted artifact or existing K1 workspace was changed by this task.
Production proceeds through the same original requirement: controlled idle load,
INSPECT, repair/check original native/provider prerequisites, prepare exact lawful
draft, engineering confirmation and PAUSE, then explicit latest-bound RESUME.
New Run/Context/claim and independent QA/Review remain mandatory. This path does
not imply the provider is healthy or that K1 has completed.

Only AUTH prerequisite failures with truthful stops are eligible. Other permanent
failure codes, unknown/live stops, unsafe draft, exhausted ordinary work or accepted
later output remain closed. Human prerequisite declaration is not automatic model
health validation. After new records exist, rollback must retain compatible readers
for the additive purpose/proof/confirmation; never drop fields, refund work,
resurrect original WorkItems or reuse an older execution approval.

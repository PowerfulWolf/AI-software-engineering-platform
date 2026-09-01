# T008 Technical Design

## Public seams

| Interface | Input | Output | Failure behavior |
|---|---|---|---|
| `AgentAdapter.run` | typed `AgentRequest` | typed `AgentResult` | provider/timeout/invalid output become typed failure; request conflict is raised |
| `FakeAgentAdapter` | scenario script + request | deterministic result | missing/misconfigured scenario raises `AgentConfigurationError` |

## Request contract

`AgentRequest` contains `run_id`, `task_id`, `role`, `attempt`, `source_revision`, `context_manifest_id`, `input_artifact_ids`, `permissions`, `output_schema`, and `timeout_seconds`. It carries only the Context manifest identity, not untrusted raw prompt text; the Context Plane remains the source of rendered input.

## Result contract

`AgentResult` echoes request identity and has `status ∈ {SUCCEEDED, FAILED, TIMED_OUT}`, optional typed `artifact`, optional `AgentFailure`, and `duration_ms`. `SUCCEEDED` requires exactly one Artifact and no failure; `FAILED`/`TIMED_OUT` require exactly one failure and no Artifact. `TIMED_OUT` requires failure code `TIMEOUT`.

## Fake scenarios

- `SUCCESS`: returns the supplied role-compatible Artifact; QA success must be `PASS`, Reviewer success must be `APPROVE`.
- `QA_FAIL`: only QA role; returns a `qa-report` with `FAIL`.
- `REVIEW_REJECT`: only Reviewer role; returns a `review-report` with `REJECT`.
- `TIMEOUT`: returns no Artifact and transient `TIMEOUT` failure.
- `INVALID_OUTPUT`: returns no Artifact and non-transient `INVALID_OUTPUT` failure.
- `PROVIDER_ERROR`: returns no Artifact and transient provider failure.

Before returning success, Fake validates task/role/kind/source revision/context manifest and verdict invariants. A scenario script is keyed by `(role, attempt)` with an optional default. Results are cached by `run_id`; exact replay returns the original immutable result, while changed request identity raises conflict.

## Test strategy

Use existing domain artifact factories with request-aligned identity copies. Test through `AgentAdapter.run` and public models only; do not mock Pydantic validators or internal cache helpers.

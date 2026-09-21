# Product failure diagnostics and explicit resume

## 1. Scope / Trigger

Structured upstream model failures in Product discussion, Console Operation error mapping,
and failure/recovery presentation. This does not authorize real model replay or state repair.

## 2. Signatures

```python
StructuredModelError(code: AgentErrorCode, safe_message: str, *, transient: bool)
StructuredModelError.with_context(context: str) -> StructuredModelError
safe_diagnostic(text: str, *, limit: int = 500) -> str
provider_error_detail(stderr: str) -> str
```

`ManagerConsoleAdapter.execute` maps this error to `ConsoleCommandRejected` with
`code="MODEL_" + error.code.value` and the bounded safe message. Existing Console Operation
`error_code/error_summary` fields and immutable records remain the wire contract; no migration.

## 3. Contracts

- Codex failures carry exit code or OS errno; Responses failures carry HTTP status and the
  structured `error.message`. Never publish stdout, whole stderr, prompt, arbitrary response
  body, validation input, raw traceback, or environment. Only an error/fatal stderr line is
  eligible; missing detail is explicit, not a guessed cause.
- Redact complete values before truncating: credentials, URL/DSN, ANSI/control characters;
  Responses must also remove its exact configured API key even if unlabeled in the response.
  Use the shared `redact_text` primitive. Final summary is at most 500 characters.
- Fallback retains existing eligibility and order; the raised error identifies the last failed
  provider/model/reasoning. Knowledge intent/assessment and final role generation add phase
  context. Invalid stage output maps to INVALID_OUTPUT without exposing Pydantic input values.
- Unknown exceptions retain MANAGER_FAILURE with a safe exception type, not `str(error)`.
  Service log correlates Operation ID with type and project module/line positions only;
  no locals, source lines or exception payloads.
- `PRODUCT_DISCOVERY` without an active Operation shows one cause/action panel in the
  discussion section, operation reference, retained-message guidance and the existing
  “继续需求讨论” action. Running operations and successfully advanced discussions hide it.
  Legacy generic summaries explicitly say the cause was not recorded. Do not infer quota.
- Explicit resume uses CONTINUE_DELIVERY and the current checkpoint. The saved user turn,
  baseline, prior failed Operation and approvals are unchanged. Never duplicate PRODUCT_REPLY,
  requeue failed Operations, reset budgets or auto-call a provider.

## 4. Validation / Error Matrix

| Input | Operation / UI |
|---|---|
| Authentication / quota / rate limit / timeout | MODEL_* category, cause and corresponding login/额度/等待 guidance |
| Start failure / provider error | Exit/errno/HTTP diagnostics; check executable, connection or route |
| Invalid JSON / typed stage payload | MODEL_INVALID_OUTPUT; remain at saved checkpoint, no approval or downstream run |
| Unrecognized exception | MANAGER_FAILURE with safe type and Operation ID for diagnosis |
| Old generic error | Cause unavailable; update/restart and explicitly resume once to obtain fresh evidence |
| Recovered clarification | WAITING_PRODUCT_REPLY, exactly one saved user turn and one Product reply |

## 5. Good / Base / Bad Cases

Good: authentication failure after saving the user turn; operator fixes login and resumes that
Requirement to clarification. Base: transient failure shows category, selected route and
recovery action without losing history. Bad: display only “已中断”, guess quota, expose raw
stderr or clear the saved dialogue to retry.

## 6. Tests Required

- `tests/web_console/test_product_failure.py`: real production preparation, file journal and
  Console with offline CLI responses; persisted cause, same baseline/dialogue on explicit
  resume, failed record reopen and no approval bypass.
- `tests/agents/test_structured_models.py`: classification, route attribution, errno/timeout/
  invalid output, HTTP details, secret redaction before bounds and stdout exclusion.
- `tests/web_console/test_core.py`: unknown safe type, correlated log, no exception secret.
- `tests/team_view/ui.test.cjs`: cause, next action, legacy compatibility, single panel and
  running/success disappearance; continue action does not resubmit user text.

## 7. Wrong vs Correct

Wrong: `except Exception: fail("MANAGER_FAILURE", "inspect durable facts")` for every provider
error, or `fail(str(error))` with unchecked transport/Pydantic contents.

Correct: map `StructuredModelError` before generic failures; persist its bounded sanitized
classification and context, and derive actionable UI guidance from the stable category.

## Incident / existing data

The September 21 Product operation retained a valid PRODUCT_DISCOVERY checkpoint but lost
its original exception. Offline replay validates saved inputs only; it cannot establish a
historical provider cause. Preserve Operation `operation_8278d20bc78fdc1cd232c297112d320f` and
Requirement `delivery_multi_bd73c5ce9fa226eaa8e427b5c7c1dd96dce1e006`. After loading this code,
the user resumes once from the UI. No manual MySQL/journal mutation or Requirement recreation.

## Bug analysis

1. **Root cause (B/D/E)**: the provider had typed errors, but Console handled them as unknown
   exceptions; the UI inferred interruption only from stage/no-active-operation. Unit tests at
   each seam did not assert that an actual provider failure retained its meaning across layers.
2. **Why a surface fix is insufficient**: changing only the interruption label cannot recover
   the discarded cause. Retrying or editing the checkpoint also cannot reconstruct it.
3. **Prevention**: typed error mapping precedes the generic catch; sanitized details are durable
   in the existing Operation. A real-journal, fake-transport regression covers fail then resume.
4. **Expansion**: the same structured client serves Designer/Planner and knowledge calls;
   diagnostics apply at that shared boundary, without changing Delivery/Coder execution policy.
5. **Capture**: this spec and task PRD record persistence, redaction, UI and recovery contracts.
   This repository has no generated spec-template tree to synchronize.

## Scenario: per-route call observations and one knowledge clarification region

### 1. Scope / Trigger

A final fallback error hides earlier primary failures and gateway latency. Repeated knowledge
buttons previously appended a new form on every click. Record completed structured calls
without changing dispatch/retry policy; present one lazy clarification region per checkpoint.
This is observability, not a fix for an upstream HTTP 504 or a model execution ledger.

### 2. Signatures

```python
capture_model_calls(sink: Callable[[ModelCallDiagnostic], None])
model_call_phase(phase: Literal["stage_reply", "knowledge_intent", "knowledge_assessment"])
FallbackStructuredModelClient(routes, *, role: TeamRole | None = None)
ConsoleOperationStore.record_model_call(operation_id: str, call: ModelCallDiagnostic) -> None
ConsoleOperationStore.model_calls(operation_id: str) -> tuple[ModelCallDiagnostic, ...]
```

`GET /api/v1/operations/{operation_id}/model-calls` returns an array of
`model-call-diagnostic.schema.json` records. No POST or retry command is provided.

### 3. Contracts

- Each `complete()` has one 32-hex `invocation_id`; `route_index` is its **configured** 1-based
  position (1 = primary, 2 = first backup), even if image filtering skips earlier routes.
- Fields: aware UTC `started_at`, optional `role`, `phase`, bounded `provider/model`,
  `reasoning_effort`, monotonic `duration_ms >= 0`, `outcome=SUCCEEDED|FAILED`, optional
  `http_status`, `request_id`, `correlation_id`, `error_code/error_summary`. A successful
  fallback does not erase its primary failure. CLI calls and transport timeouts have no
  invented HTTP metadata. Arbitrary uncaught exceptions are not synthesized as completed calls.
- HTTP metadata allowlist: `x-request-id` (or `request-id`) and `x-correlation-id` only.
  IDs must match `[A-Za-z0-9_.:-]{1,128}`; reject credential echoes and secret-like strings.
  Never persist headers, prompts, response bodies, endpoint URLs, API keys or environment.
- Console binds the observer around `executor.execute` and resets it in `finally`.
  ContextVars isolate concurrent operations. Current production supervisor invokes structured
  workers in the same thread; future thread/process execution must explicitly propagate
  observations. Background heartbeat threads are not model callers.
- File records live in `<operations>/<operation-id>/model-calls/<record_sha256>.json`.
  `ConsoleModelCall` hashes its canonical `operation_id + call` envelope. Publish atomically;
  exact replay is idempotent, and Operation sequence/hash/checkpoint records are unchanged.
  Require a RUNNING operation on write, at most 2048 records, and at most 16 KB per read.
  Reads verify envelope identity, content hash, regular files and absence of symlinks.
- Observation storage failures log only the Operation ID and do not fail, replay or bill
  the underlying model call again. This is not an exactly-once ledger: process termination
  during an unfinished call may leave no record. Old operations return an empty array;
  never backfill invented observations. Only Console-scoped structured calls are persisted,
  not arbitrary Coder/QA tool subprocesses or standalone CLI invocations.
- Knowledge UI caches one section per `(project_id, requirement_id, checkpoint_sha256)`,
  with at most 20 nearby sections. One in-flight GET, then toggle visibility; failed GETs
  replace the feedback and permit retry. Deduplicate by `gap_id`; polling/reopening the same
  checkpoint retains drafts. Changing checkpoint creates a new section, and old asynchronous
  results cannot populate it. Cache eviction/reloading the page is not durable draft storage.
- Long questions are ordinary wrapping paragraph text, not headings. Use numbered short
  card headings, explicit answer/source labels and one feedback area. All values use
  `textContent`. Approval keeps the exact gap, answer digest and original endpoint; duplicate
  submits are guarded. Approval does not automatically continue delivery.

### 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Primary HTTP 504, backup HTTP 200 | Two records, same invocation, configured route order, separate durations/IDs |
| Timeout / CLI result | HTTP status and request ID absent, never guessed |
| Unknown operation | GET 404 |
| Old operation without diagnostics directory | GET 200 with `[]` |
| Altered hash/identity, symlink, invalid record or non-directory | GET 409; operation/journal unchanged |
| Sidecar write failure or record limit | Safe correlated log; underlying delivery result unchanged |
| Repeated or concurrent view clicks | One region, at most one in-flight request |
| Resolution failed / retried | One feedback region, answer/source drafts retained |

### 5. Good / Base / Bad Cases

Good: backup succeeds and the operator can still inspect primary 504 duration/request ID.
Base: no gateway ID is supplied, so the UI says it was not provided. Bad: invent an ID,
replay a model to produce historical diagnostics, or append duplicate approval forms.

### 6. Tests Required

- `tests/agents/test_model_diagnostics.py`: complete primary/fallback chain, image-filtered
  route numbering, timeout and phase reset, concurrent isolation, header/secret filtering,
  Python/JSON Schema parity with positive and negative payloads.
- `tests/web_console/test_model_calls.py`: real fallback with fake HTTP transport through
  Console -> file sidecar -> reopened GET; hash/symlink/path rejection, 404/405/409,
  no original Operation hash changes, and sink failure without retry or delivery failure.
- `tests/team_view/knowledge-gap.test.cjs`: one GET/form, retry/submit single-flight,
  draft retention, late responses across checkpoints and safe diagnostic presentation.

### 7. Wrong vs Correct

Wrong: capture only the last exception, renumber routes after image filtering, or
`button.onclick = () => panel.append(newForm())`.

Correct: observe each completed configured route; keep the immutable execution record
separate from diagnostics; toggle and update one checkpoint-scoped region with load guards.

### Existing data and bug-prevention record

No database or historical journal repair is needed. When no operation is executing, restart
Console with the existing config/credential/CA environment and refresh the browser. Existing
requirements and pending knowledge gaps remain usable. New calls produce diagnostics; old
missing gateway IDs cannot be recovered. The user triggers any resume in the platform.

Root categories are B (HTTP metadata lost between transport, fallback and Console) and D/E
(tests and UI assumed a single click). Merely renaming errors or reducing heading size would
leave these defects. Typed metadata plus an end-to-end fixture prevents diagnostic loss;
checkpoint-keyed sections and concurrent-click tests prevent duplicate forms and cross-request
responses. The shared structured client covers other upstream roles without changing their
authority. This spec and its task PRD capture the contracts; no generated spec templates exist.

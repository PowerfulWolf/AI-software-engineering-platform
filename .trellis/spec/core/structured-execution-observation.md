# Structured execution observations

## 1. Scope / trigger

Use when structured knowledge/Product/Design/Planner calls need trusted admission
and actual local completion evidence. This additive Agents seam does not authorize
retry, inspect a Task, change a queue, create recovery records or claim a verdict.

## 2. Signatures

```python
class StructuredExecutionObserver(Protocol):
    def admit(self, admission: StructuredExecutionAdmission) -> None: ...
    def native_stopped(self, receipt: StructuredNativeStopReceipt) -> None: ...
    def native_not_started(self, receipt: StructuredNativeNotStartedReceipt) -> None: ...
    def http_completed(self, receipt: StructuredHttpRoundTripReceipt) -> None: ...

bind_structured_execution_observer(observer: StructuredExecutionObserver) -> contextmanager
structured_call_identity(identity: StructuredCallIdentity) -> contextmanager
structured_request_digest(*, instructions: str, input_payload: Mapping[str, object],
    output_schema: Mapping[str, object], timeout_seconds: int,
    image_sha256s: tuple[str, ...] = ()) -> str
```

Models and helpers live in `agents/structured_observation.py`. Each immutable model
has `create`, `to_wire`, `recompute_sha256`, `validate_integrity`. The independent
`schemas/structured-execution-observation.schema.json` exactly matches
`TypeAdapter(StructuredObservationRecord).json_schema()` plus `$schema`/`$id`.

## 3. Contracts

- Fallback binds every actual route with one shared invocation ID, distinct route
  index and observation ID, actual provider/model/reasoning/type/connection, role
  and `current_call_phase`. Request digest covers instructions, exact input/schema,
  timeout and verified image byte digests. No prompt, credential, environment,
  payload, stdout/stderr, response body or raw error text is in an observation.
- Before spawning or posting, an observer receives and persists an admission with
  that identity, transport-request digest, timeout and admission time. An observer
  bound without a route identity rejects before execution. No observer preserves
  existing behavior and does not create historical receipts.
- Native bridge uses `SubprocessCodexCommandRunner.run_observed`. After the owned
  runner proves its process group absent, the callback validates the real
  `NativeProcessStop`, return code and timeout kind and persists a receipt bound to
  the complete admission. Output hashes represent the runner's bounded returned
  text. Publication precedes TimeoutExpired/CalledProcessError, adapter parsing,
  or return. No callback/unknown ending creates no stop and rejects acceptance.
- Native startup has a separate `StructuredNativeNotStartedReceipt`, bound to the
  full admission, typed `input_preparation_failed` / `process_spawn_failed` and
  failure time. Only the owned runner's `CodexProcessNotStarted` establishes it:
  an input-preparation or Popen `OSError` before Popen returned a process. It has
  no PID or NativeProcessStop and cannot close a historical unknown execution.
  Generic CodexCliError/OSError does not establish not-started. After Popen, prompt
  close or ownership-registration failures enter owned process cleanup, publish
  real stop facts if proven, then fail as execution uncertainty without provider
  fallback. Unknown cleanup creates neither synthetic stop nor not-started.
- HTTP publishes a separate local synchronous round-trip receipt after transport
  return or typed TimeoutError/OSError and before error/output interpretation.
  The receipt means only that the local call returned, including a response hash
  or a stable exception category. It **does not prove remote work stopped**, has no
  NativeProcessStop, and cannot substitute for a native shutdown receipt. Unknown
  BaseException or killed Host produces no invented completion.
- Observer writes are synchronous. Any ordinary callback exception is wrapped as
  `StructuredObservationRejected`, outside OSError and StructuredModelError;
  provider fallback cannot conceal failed persistence. BaseException also escapes.
- Observer and route binding use independently reset ContextVars. They are scoped
  trusted composition facts, never model input or execution permission. Existing
  ExecutionGuard, process ownership and provider policy remain authoritative.
- Knowledge composition must independently bind these records to the real exact
  request/Task/claim/authorization and enforce exact role/phase. Standalone role
  may be null. Observation alone grants no execution, continuation or retry.

## 4. Validation matrix

| Scenario | Required behavior |
| --- | --- |
| Native success / nonzero / local timeout | Admission then real native stop before output/error translation |
| Native invalid structured JSON | Stop remains published; output is still rejected |
| Native executable / input-preparation failure before Popen success | Admission then separate NOT_STARTED receipt; valid provider fallback may continue |
| Popen succeeds, ownership registration fails | Actual owned cleanup and real stop if proven; no NOT_STARTED or provider fallback |
| Unknown process end or missing callback | Admission only; no synthetic stop or accepted output |
| HTTP success / invalid JSON / error status | Local round-trip receipt before interpretation; no native stop |
| HTTP TimeoutError / OSError | Stable local transport-error receipt; no remote-stop claim |
| Any observer publication fails | Fixed observation rejection; backup route never called |
| Nested/concurrent bindings | Correct observer only, tokens restored on all exits |
| Digest/transport kind/time mismatch | Reject model or integrity validation |

## 5. Good / base / bad

Good: real owned process timeout is sealed before converting it to a local execution
limit; a later knowledge service consumes that exact authorized fact. Base: without
an observer, legacy behavior is unchanged. Bad: infer a native stop from elapsed
time, HTTP timeout, absent PID, observer admission, or a structured result alone.

## 6. Tests and checks

`tests/agents/test_structured_observation.py` uses real temporary executable/native
processes for success, nonzero, timeout and JSON rejection. It verifies fallback
route identity, separate HTTP receipts, publication failures, context isolation,
shared request hashing, Schema equality and digest tampering.
The startup regressions use a genuinely absent executable, a fenced fallback
observer, injected input preparation failure and post-Popen ownership failure;
they assert complete per-route facts and reaped fixture children. Existing structured
execution/model/diagnostic tests remain required. Run only these incremental files,
Ruff and strict mypy on the touched production code/tests.

## 7. Existing data / rollback / prevention

No SQL or historical record migration. Old unknown executions remain unknown;
never backfill guessed starts/stops. The optional observer must be installed by
trusted authorized composition before it can persist future facts. This layer
alone does not complete current knowledge recovery or resume a Requirement.
Rollback optional wiring while idle; retain all newly sealed observations and
original audit records. The previous failure mode was a subprocess compatibility
bridge dropping trusted stop evidence before raising/JSON parsing. Keep regression
tests at that actual bridge and production structured-client boundary.

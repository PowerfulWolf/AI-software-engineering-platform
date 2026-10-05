# Responses strict wire contract

## 1. Scope / Trigger

Use when changing `agents/responses.py`, shared HTTP diagnostics, or exposing Delivery role errors in Console.
Reference: https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas

## 2. Signatures

`_request_body(...) -> bytes`, `_artifact_schema(role) -> dict[str, object]`,
`_decode_artifact_output(content: str) -> Artifact`, `http_error_detail(body: bytes, api_key: str) -> str`.
No domain Artifact Schema or persisted Task/verdict contract changes.

## 3. Contracts

- Every strict function parameter object's declared properties must all be required; reuse
  `strict_output_schema` for tools as well as final output. No open `additionalProperties` objects.
- The bounded tool loop is stateless (`store=false`, no `previous_response_id`). Every next request
  includes the original messages, all prior assistant output items (including opaque reasoning),
  and exact `function_call_output` receipts. Only new calls execute; historical outputs are context,
  not another tool dispatch. Output cannot introduce system/user instruction roles.
- Strict response roots are objects. The provider envelope is exactly `{"artifact": ...}`;
  Coder's progress/implementation union lives below this object, never at the root.
- QA's optional free-form `content.environment` is a JSON-encoded object string (or null) on the
  provider wire. Decode it before normal domain validation. Historical/bare domain reports remain
  readable; no verdict, evidence, producer or candidate repair is allowed.
- HTTP diagnostics read only a JSON `error.message`, redact the configured key and generic secrets
  before truncating to 240 characters, and never expose raw HTML/body/prompt or credential URLs.
- `ManagerConsoleAdapter.execute` maps `AgentRunFailed` to `MODEL_<typed code>` with bounded,
  sanitized role/cause. Unknown exceptions still use safe MANAGER_FAILURE handling.
- Responses Coder routes receive the same trusted `CoderInterruptionControl` as Codex routes;
  QA/Reviewer never receive this capability. Before a provider call the adapter performs exact
  `prepare` and `started`; a successful final response uses `finished` before candidate finalization.
  With frozen v2 authority, synchronous transient failure or a local execution limit may seal
  `SynchronousToolLoopStop` plus the complete legal mutation receipt and return `WORK_INTERRUPTED`.
  The stop binds the exact request and all sequential completed tool operation IDs. It has no
  fabricated process PID and cannot substitute for unknown subprocess or owner-loss facts.
  Fresh claim/Run/Context and the original frozen budget are mandatory for continuation.
  Without trusted control, a dirty failure retains `POLICY_VIOLATION` and safe diagnostics.
  A legacy v1 control may return preservation-only `WORK_INTERRUPTED`, but cannot seal the
  v2 synchronous stop or authorize automatic continuation. Both need exact engineering
  investigation. Neither path allows dirty fallback within the same Run,
  reset, artifact acceptance or QA/Review admission.
- One monotonic deadline starts with the adapter invocation. Every HTTP timeout and actual
  restricted command timeout is bounded by the remaining time, including later turns.
  Window/turn/tool bounds are `local_execution_limit`, never provider transient refunds.
  Provider timeouts before this deadline retain their typed provider cause. Policy refusal,
  unknown command process/drain or lost owner do not seal a synchronous stop. A final body
  already present when finishing exceeds the window remains preserved for engineering;
  it cannot be claimed absent to authorize another run.
- `UrllibHttpTransport` binds per-call stdlib HTTP/HTTPS response readers to the remaining
  deadline. Status lines, headers, chunk framing and 2xx/error bodies use bounded `read1`;
  each real socket read updates its timeout to the remaining time. A slow continuous stream
  therefore cannot renew the whole window. The reader remains synchronous and bounded in
  bytes; it neither launches background requests nor synthesizes completion for running tools.
  Exact model endpoint redirects are returned as HTTP errors instead of changing POST to GET
  or forwarding bearer authority. Buffered HTTPError fixtures retain diagnostic/header behavior.
- An admitted failed verification run remains consumed. Changing adapter code never permits replay;
  the next live verification uses a fresh exact plan and approval through the ordinary entry.
- Codex CLI `_validation_rule(error: ValidationError) -> str` maps the first validation error
  to a fixed allowlisted rule code. Diagnostics contain `validation_rule`, never the raw error
  message, rejected input, unknown evidence IDs, or full provider report. Unrecognized rules
  return `UNCLASSIFIED`; validation remains fail closed with no artifact and no verdict repair.

## 4. Validation & Error Matrix

| Input | Expected behavior |
| --- | --- |
| Tool property omitted from required | Outbound-schema regression fails before live call |
| Gateway does not retain response IDs | Complete tool exchange via local bounded transcript |
| Coder anyOf root or QA arbitrary object | Provider-only envelope/metadata encoding; domain unchanged |
| Environment string is malformed JSON, null JSON, or an array | INVALID_OUTPUT; no Artifact |
| Envelope has extra fields | Reject, do not silently discard |
| QA PASS with NOT_TESTED criterion | Existing domain validation rejects |
| HTTP 400 with structured message | MODEL_PROVIDER_ERROR and safe detail; no blind fallback |
| Raw/non-JSON response body | Generic bounded message, never raw body |
| CLI semantic report error | Fixed rule code plus existing type/root/hash; no private values |
| Unknown CLI validation message | UNCLASSIFIED; no arbitrary message or value leakage |
| Provider route fails after legal tool writes under v2 authority | WORK_INTERRUPTED; exact synchronous stop and full draft; fresh claimed continuation, no same-Run fallback |
| Provider route fails without authority or after policy refusal | POLICY_VIOLATION; no fabricated stop/approval, preserve workspace |
| Provider route fails with legacy v1 control | Preservation-only WORK_INTERRUPTED; no v2 receipt or automatic continuation |
| Later HTTP/tool turn | Timeout never exceeds remaining invocation window |
| Window or bounded loop exhausted | local_execution_limit, frozen work allowance; no provider failure refund |
| Tool descendants/drain or claim uncertain | Typed uncertainty/owner loss propagates, no stop or additional provider call |

## 5. Good/Base/Bad Cases

Good: QA metadata round-trips exactly and verdict guards still run. Base: an older compatible
provider returns a bare report; full domain validation still applies. Bad: disable strict mode,
drop untested criteria, or replace API failures with fabricated PASS evidence.

## 6. Tests Required

`tests/agents/test_responses.py` checks all roles' actual outbound tool/schema shapes, wrapper
round-trip, metadata preservation and invalid verdict/environment/envelope rejection.
`tests/web_console/test_manager.py` checks typed role failures and secret redaction.
Shared structured-model/diagnostic tests must continue to pass after extracting HTTP detail logic.
`tests/agents/test_responses_continuation.py` uses actual PolicyBoundToolRegistry, Git, SQLite,
immutable v2 stores and claim fixtures, with only HTTP/time ports scripted. It covers dirty
provider failures, exact stop/source/operation binding, same-branch fresh continuation,
deadline caps and budget attribution, forbidden fallback, policy refusal and execution uncertainty.
`tests/agents/test_http_deadline.py` uses a real loopback HTTP server: success/error body drip,
status/header drip, normal responses, body byte bounds, exact endpoint redirect and invalid
window rejection. This verifies transport behavior without a production provider.
The scripted provider must reject `previous_response_id` like a stateless gateway; assert initial
context, reasoning, call IDs and receipts are retained in order with no repeated command execution.
`tests/agents/test_codex_cli.py` must reject missing evidence, inconsistent QA verdict and wrong
producer while exposing distinct constant rule codes, preserving unknown-error redaction and
same-run replay. This diagnoses invalid output; it does not make invalid output acceptable.

## 7. Wrong vs Correct

Wrong: `strict=true` with `properties={path,max_bytes}` but `required=[path]`; root `anyOf`;
free-form QA dict sent directly to strict API; swallowing AgentRunFailed as unknown Manager error.

Correct: normalize every tool schema; use a closed artifact envelope and adapter-only metadata
codec; run unchanged domain validation; retain safe typed failure detail through Console.

Conversation reference: https://developers.openai.com/api/docs/guides/conversation-state

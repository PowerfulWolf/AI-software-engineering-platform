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
- A Responses provider failure that leaves a Coder worktree dirty keeps the
  `POLICY_VIOLATION` classification and appends a bounded `provider_diagnostic=` detail after
  secret redaction. The safety guard still forbids fallback, reset, automatic retry, artifact
  creation, and QA/Review admission; the preserved worktree must go through an exact recovery
  plan and human approval.
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
| Provider route fails after writing worktree changes | POLICY_VIOLATION with bounded provider detail; preserve worktree and require exact recovery approval |

## 5. Good/Base/Bad Cases

Good: QA metadata round-trips exactly and verdict guards still run. Base: an older compatible
provider returns a bare report; full domain validation still applies. Bad: disable strict mode,
drop untested criteria, or replace API failures with fabricated PASS evidence.

## 6. Tests Required

`tests/agents/test_responses.py` checks all roles' actual outbound tool/schema shapes, wrapper
round-trip, metadata preservation and invalid verdict/environment/envelope rejection.
`tests/web_console/test_manager.py` checks typed role failures and secret redaction.
Shared structured-model/diagnostic tests must continue to pass after extracting HTTP detail logic.
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

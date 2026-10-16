# Contract and implementation seam

## Signatures and wire

Existing `CodexCliAgentAdapter.run(request) -> AgentResult` is unchanged. For the ordinary
nonzero provider-failure return only, append `; main_error=<JSON string>` to AgentFailure.message.
Decoded string is a selected safe summary of at most 500 characters, or an explicit unavailable
message. `_failure_diagnostic` remains the original cause/returncode/stdout-SHA/stderr-SHA helper.
`_classify_cli_failure` sees the original invocation and its return tuple is unchanged.

The adapter knows the configured proxy credential's environment name and already filtered
environment. Remove its complete exact value in memory before redaction/selection. When a
proxy is configured but that value is absent/empty, hide all new detail. No credential lookup
outside the existing controlled mapping. No credential or raw transcript enters a store/log.
The shared `safe_diagnostic(text, *, limit=500, exact_secret=None)` keeps its bounded default;
when exact_secret is supplied, remove it before cleanup and again after complete normalization,
before truncation. ANSI/OSC removal can reconstruct a split key. Do not add an unbounded output
mode or truncate a key first. Native proxy summaries with unresolved escape forms fail closed.
Proxy keys containing whitespace or nonprintable characters also hide details; formatting can
alter the configured value itself, so exact reconstruction is not a trustworthy display boundary.

## Selection and validation

Redact the complete bounded stderr before selecting the existing trusted native main diagnostic,
then apply URL/control/credential sanitization to the complete selected summary before bounding.
Only complete, untruncated input qualifies. Never promote stdout, MCP/background logs or arbitrary
lines. For a main JSON object, allow only a string `error.message` or top-level `message`; do not
render sibling request, prompt, stack, body, headers or environment. Non-JSON main text uses
the existing native main-error provenance. Unavailable/incomplete/foreign input stays explicit.

Only the new ordinary provider-failure branch gets a detail. Dirty policy, timeout, authority
abort and native-stop proof behavior remain unchanged. Existing durable ModelRouteAttempt and
DeliveryInvocationOutcome already persist AgentResult, so no Schema or migration is needed.

Python `team_view.blocker_text._role_failure` and JavaScript `humanizeBlockingText` consume the
optional single JSON-string marker from the original role-failure text. Reject missing/invalid/
non-string markers, bound the decoded display and preserve old Run/hash display. HTML remains
textContent. Marker affects display only, never classification, authority or retry eligibility.

## Validation matrix

| Input | Expected result |
| --- | --- |
| Complete main Error/fatal or supported provider single message | Safe bounded detail, unchanged category/transient |
| Complete main JSON error.message/message plus unrelated fields | Message only; siblings absent |
| Exact proxy key, private key, labeled token, URL, ANSI/control | Redact before selection/truncation; no clear secret |
| Missing/empty configured proxy key | Detail unavailable |
| stdout, MCP, background timestamp, no main, truncated/incomplete | Detail unavailable; no guessed cause |
| Dirty policy/timeout/abort | Original hash-only metadata behavior |
| Typed result + file route/outcome store reopened | Same safe message and immutable identity |
| Old hash-only role failure | Existing display without invented detail |
| JSON marker object/array/invalid, long text or HTML | Reject wrong type; bound safe text; no HTML execution |

## Existing data and rollback

Do not modify two old K1 failed outcomes, stop records, queue dispositions or unknown history.
Prepare any next exact plan from current actual stopped facts, deploy at idle, PAUSE then separately
RESUME within frozen ordinary budget. Diagnostic execution can still fail; only its new sealed
detail can establish a new cause. No automatic unknown retry, refund or skipped QA/Review.

# Frozen design: raw native JSON diagnostic observation

Signatures and executable contracts are recorded in core/native-cli-unknown-failure.md. Trusted runner construction explicitly enables codex_json; default off and run/run_observed signatures unchanged. One line buffer (65536 raw bytes) and one candidate; strict duplicate/UTF8/object/finite-number/depth32/surrogate validation. Any malformed or incomplete line poisons the entire invocation. Root error/turn.failed only, new turn/completed clears candidate. Ordinal/SHA cover original complete lines. Each runner call has independent observer state.

CodexEventClassification(source, code, transient, timeout_provider_failure=False, main_error=True) is computed from the complete original message using caller-specific existing matchers. CodexJsonFailure adds event_type, ordinal, event_sha256, complete, classification and repr-excluded safe message. Classification occurs before full exact-secret/private-key/URL/control cleanup and bound; display cannot become authority. Native and structured retain different classifiers and watchdog priorities; MCP/RMCP/tool prefixes cannot establish AUTH/RATE/provider-before-watchdog.

Native drain observes original stdout before decoder/head-tail. Runner publishes same-call metadata only after actual EOF plus owned-session stop, before stop recorder and existing resource cleanup/ownership-clear ordering. Structured returns private CompletedProcess/TimeoutExpired subtypes carrying exact invocation, sharing observer while keeping caller classification.

One intentional security boundary change: structured no longer trusts arbitrary injected/bounded stdout JSON. Its old fake stdout tests now explicitly prove no authority; real original-stream 401/429/503/504 and watchdog tests preserve existing behavior. Existing stderr matching remains.

Actual red: unchanged-source real adapter argv test lacked --json, 1 failed in 0.89s. Correct actual offline child emitted >1.6MB stdout/stderr with complete root turn.failed in discarded middle; unchanged actual adapter returned PROVIDER_UNAVAILABLE/nontransient+detail unavailable instead of RATE_LIMITED, 1 failed in 1.13s through normal approval. Initial sandbox test was inconclusive OwnedSessionUnknown; it is not claimed as the bug reproduction.

No Schema/DB migration or historical rewrite/refund/recovery approval. Parent alone handles K1/production/release. Code is prepared in /tmp for normal reviewed application to the authorized maintenance worktree; no bypass of permission review.

Independent review caught and reproduced a component-event shadowing regression: event MCP: authentication 401 plus real stderr HTTP503 changed transient true to false (1 failed in0.15s). `main_error=False` now excludes such component events and restores stderr fallback; genuine unknown root errors are unaffected. Both callers and watchdog stderr compatibility are covered.

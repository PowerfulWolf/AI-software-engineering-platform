# Preserve safe native Delivery failure detail

Goal: new nonzero native Delivery failures must retain a bounded, redacted selected main
diagnostic in their existing AgentFailure.message, then existing immutable route/outcome stores.
The two K1 UNKNOWN_EXIT histories retain only hashes and cannot be reconstructed or rewritten.

Allowed paths: src/ai_software_engineer/agents/codex_cli.py, agents/diagnostics.py if needed,
tests/agents/**, tests/work_queue/test_invocation_journal.py, tests/model_router/**,
src/ai_software_engineer/team_view/{blocker_text.py,app.js}, tests/team_view/**,
.trellis/spec/core/{native-cli-unknown-failure,product-failure-diagnostics}.md and this task directory.
No production draft writes.

Acceptance:
- A new real adapter rc1 failure retains a useful safe selected main diagnostic across typed
  result serialization, route/outcome store reopen, including unknown nontransient failure.
- Only complete native main stderr diagnostics qualify. No stdout, arbitrary transcript,
  background MCP/tool logs, raw JSON siblings, prompt, incomplete/truncated body or traceback.
- Redact complete input before selection; exact configured proxy key must be removed before
  formatting as well as normal credential/private-key/URL/control redaction before truncation.
- Diagnostic detail is at most 500 characters, with an explicit unavailable marker otherwise.
- _classify_cli_failure, flags, budgets, refunds, stopped-process authority and error-code
  interpretation remain unchanged. Existing hash/cause/rc metadata remains available.
- Policy-violation/timeout/guard-abort paths must not gain uncontrolled provider text.
- Old immutable bytes/digests are not rewritten; no Schema or database migration.

Tests: establish RED with real adapter selected safe message lost; GREEN targeted diagnostics,
native failure classification/proxy/privacy, serialization/reopen; Ruff/format/targeted mypy;
read-only independent review. No real provider needed for tests.

Production: deploy only at verified idle boundary via controlled restart; inspect fresh
facts and obtain a new exact same-Task PAUSE/independent RESUME for one remaining ordinary
attempt if diagnostic execution is needed. Never loop unknown retries or call completion DONE.

Rollback: code revert before new publication; afterwards retain compatible readers and use
controlled pause/forward fix. No deletion of failure history, reservations, audits or drafts.

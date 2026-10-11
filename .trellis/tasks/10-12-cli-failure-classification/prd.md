# Native CLI main-execution failure provenance

## Goal and observed limits

The native Coder CLI stderr contains both main-execution errors and background MCP startup/log
diagnostics. `_recognized_cli_failure` currently slices from the first substring `error:` through
the entire remaining stderr and searches every quota/rate/auth marker. An unrelated MCP 401 or
login hint can therefore classify a different main failure as nonretryable authentication.

Root observed a successful bounded health execution whose stderr had auth words/statuses. The
earlier failed execution retained only stream digests, so this fix cannot establish or rewrite its
historical first cause. No production API/SQL/model/K1 access is permitted for this task.

## Scope and design

- Own native CLI diagnostic selection/classification, focused adapter/fallback tests and this
  task/organization spec in `/ase-cli-failure-classification` from `05cb35b`.
- Select a bounded **main diagnostic block**, anchored at the actual unprefixed terminal
  `Error:`/`Fatal:` or HTTP diagnostic. Do not scan MCP component, timestamped background logs,
  model/tool transcript or stdout as provider evidence.
- Preserve genuine multiline provider diagnostics and existing bare single-message quota/rate/auth
  compatibility. Unknown nonzero exits keep existing PROVIDER_UNAVAILABLE classification; this
  changes neither fallback strategy nor retry policy.
- Successful/signalled executions cannot establish a provider failure from stderr words.
- Parent authorized the smallest capture-provenance addition after review: record actual stderr
  truncation as a typed process-result flag without changing retained text/digests or stop proofs.
  Only complete lines in the retained tail may establish a main diagnostic after truncation;
  unknown truncated failures cannot grant transient fallback authority.
- Keep workspace mutation/policy rejection, exact stop ownership, receipts, output validation,
  immutable history and secret-free diagnostic digests unchanged.
- Other agents are working. Do not overwrite their changes or edit main/production facts.

## Acceptance and verification

1. Minimal false-auth tests fail before code changes.
2. MCP 401 noise before/after a distinct primary error cannot create authentication, quota, rate or
   invalid-output classification. A genuine root auth, multiline auth or JSON provider error remains
   nonretryable auth even with unrelated background logs.
3. Real adapter + durable fallback fixture uses unchanged workspace and same existing fallback
   policy; actual auth and changed-workspace/unknown-stop cases retain their rejection.
4. Diagnostics retain only fixed categories/exit/digests, without raw stdout/stderr or credentials.
5. Incremental tests, Ruff/typecheck, spec sync and independent review pass; no full test suite,
   production model call, service restart or historical facts rewrite.

## Rollback / existing data

Root integrates and deploys only at its controlled idle boundary. Revert this code before future
invocations to roll back. No Schema/SQL/history migration or new approval is introduced. Existing
failed runs remain immutable. This selector change alone cannot continue a retained stopped,
nontransient Run; Root owns the separate exact, human-authorized ordinary-work continuation gap
and existing-data disposition. A historical stderr digest cannot reconstruct the omitted transcript
or prove that authentication was false.

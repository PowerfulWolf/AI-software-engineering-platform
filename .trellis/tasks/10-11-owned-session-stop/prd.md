# Owned session stop coverage

## Goal and scope

Replace the leader-PGID-only cleanup predicate with one trusted controller for every
currently registered actual Popen spawn. A same-SID child in another process group
that closes both inherited output pipes must be stopped before publication or Host
drain can succeed. Keep EOF, leader reap and complete owned-session absence separate.

No model, production database, ASE Operation or existing sidecar is accessed. No
arbitrary PID signal tool, dependency, permissions expansion or historical proof
upgrade is introduced. Previously observed children leaving the SID remain unknown;
unobserved setsid descendants are outside this proof's scope.

## Acceptance and verification

- Real native/structured/tool/verification subprocess tests reproduce the silent
  same-SID different-PGID case; TERM-resistant children require KILL escalation.
- Bounded incomplete enumeration, inspection denial, birth/boot drift and changed
  ownership remain unknown, retain the registry and prevent service READY.
- Only a capability created from the actual isolated Popen may signal identities
  freshly verified in that same session. OS identity checks precede each signal.
- New NativeProcessStop optionally carries a versioned owned_session_empty proof;
  absent proof is omitted by serialization and preserves historical stop/enclosing
  digests. All ten embedded Schemas and canonical regeneration guards agree.
- Existing cancellation, owner-loss, EOF failure and stop-save failure regressions
  remain enforced. Run only scoped pytest, Ruff and strict mypy; no MySQL tests.
- Host ownership remains finalizing through actual command evidence put, outer run
  manifest seal and verification receipt put. Failure/no confirmation retains
  uncertainty; nested scopes and trusted proxy workers cannot clear it early.
- Capture failures retain no raw traceback/payload. All observation histories and
  finalization references are bounded and released at scope exit.

## Allowed paths

`src/ai_software_engineer/owned_sessions.py`, `owned_processes.py`,
`agents/{execution,codex_cli}.py`, `execution.py`, current registered subprocess
consumers in `agents/` and `manager/`, `orchestration/continuation.py`, related
`scripts/*schema*.py`, the ten schemas embedding NativeProcessStop, dedicated
`evidence/capture.py`, `recovery/verification_execution.py`, `tests/execution/`,
`tests/agents/`, `tests/contracts/`, `tests/recovery/test_native_ui.py`,
`.trellis/spec/core/`, `.trellis/spec/guides/recovery-thinking.md`,
`docs/architecture/contracts.md` and this task directory. The evidence/recovery
extension was explicitly authorized by root before implementation.

## Rollback and existing data

Only root integrates and deploys after independent review, at an idle controlled
restart boundary. Rollback the code commit before starting new invocations; retain
new optional stop proof bytes and all original historical records. No data migration
or backfill: old stops retain their leader/group scope. Existing recovery still
requires its current-fact checks and exact approval chain. A reverted reader must
support new optional proofs before reading new records; never strip proof bytes to
change a digest. This task does not resume K1.

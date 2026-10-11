# Design

The actual-spawn controller and Host durable finalization are private trusted
composition seams, not Agent tool permissions. The executable contract is recorded
in `.trellis/spec/core/owned-session-stop.md`.

## Actual spawn and OS identity

`OwnedSessionController(Popen)` captures PID=PGID=SID, boot identity and kernel birth
immediately after Popen and before reap. Darwin uses bounded libproc/BSD inspection;
Linux uses bounded /proc kernel ticks. Two complete SID observations and current
identity checks precede individual peer signals. Finite TERM/KILL phases succeed
only after leader reap and two complete empty observations. EOF and worker exit
remain separate facts. Native active-owner polling records existing peers.

Previously observed PID/birth identities are rechecked around every scan and before
signals. A living original birth migrating out of the SID remains unknown; a recycled
nonleader PID is absent under its old birth and cannot be signalled. Observed identity
history is bounded to 16,384 entries, scan to one second/16,384 processes, and streaming
observation count to 1,000,000. Query-to-signal is not atomic kernel containment.
Unobserved setsid escape remains explicitly outside scope.

## Wire compatibility and read recheck

Optional `NativeProcessStop.session_proof` is excluded when absent/null, including
ordinary nested model_dump, so old stop/enclosing digests remain unchanged. Proof
binds v1/fixed scope, leader, boot, sorted observed births, streaming observations
digest/count/time and its own digest. Exact leader/time/integrity are validated.
Canonical completed/failed returncode Schema guards survive all ten embedded copies
and fresh repair generation. The sync script preserves unrelated enclosing guards.

Read-only `require_recorded_session_empty` checks the current boot, conservative
leader occupancy, every original observed birth and complete SID twice, without any
signal capability. Old stops retain their existing group check; no backfill occurs.

## Durable ownership

`OwnedRecordFinalization` holds stopped observations while the real trusted store
put/run seal is pending. An explicit `confirm_saved()` follows the actual successful
put/seal. Nested successful scopes transfer observations upward; they cannot remove
registry ownership before the outer seal. Up to 4,096 deduplicated observations are
retained per scope, then all observation/parent references are cleared at exit.
No save, failed save, late/duplicate confirmation or overflow preserves uncertainty.

| Consumer | Save responsibility |
|---|---|
| Native Codex | actual observer stop publication before stopped recheck |
| Command evidence | exact FileEvidenceStore put after actual executor completion |
| Agent evidence wrapper | result evidence and actual run manifest seal |
| Swift verification | resource/command cleanup then exact COMPLETED/BLOCKED receipt |
| Python/MySQL verification | proxy/resource/command cleanup then exact receipt |
| Git/OS/DEVNULL query | no fabricated publish obligation; actual stop/EOF completion |

MySQL proxy worker threads explicitly inherit the trusted operation/finalization
contexts. Controller serialization protects concurrent close/worker cleanup, and
pipe workers must terminate before stopped observation. These consumers are statically
checked only; no MySQL tests/resources were accessed in this task.

Capture failures store a flag instead of a raw exception/traceback. Registry snapshots
contain only bounded identities/state/reason, never the ownership controller or
interrupted caller payload. Real weakref regression proves caller payload release.

## Delivery boundary

This isolated worktree is based on e4023c47b7194513a3ab3bb1b05951f89baf58f5. Main checkout,
production Run, database/sidecars and model calls remain untouched. Root independently
reviews, integrates and deploys only at an idle controlled boundary. No historical
state or proof migration; K1 recovery continues through its existing authorized path.

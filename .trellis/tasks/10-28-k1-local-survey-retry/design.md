# Design

## Cause

The current sealed K1 recovery source is valid, but the complete local survey can
intermittently report `PROCESS_SCAN_INCOMPLETE` at `paths_before` or
`process_identity_final`. Existing `observe` returns that single result, and
`require_idle` correctly blocks recovery. The fixed survey has a 5-second deadline
and each ps/lsof query keeps its 1.5-second cap. Raising those caps or treating a
partial survey as idle would weaken the authorization gate.

## Contract

`observe` performs at most three calls to a private `_observe_once`. A retry is
allowed only when `_observe_survey_worker` returned a fully validated typed result,
after `finish_owned_process` proved the worker session stopped, with an
`incomplete_phase` and sole blocker `PROCESS_SCAN_INCOMPLETE`. The next attempt
recomputes root, parent identity, request SHA and deadline. A synthetic incomplete
result from a parent/protocol/cleanup error is terminal for this call.

No exception detail, process path, PID or raw lsof is returned. Each failed attempt
keeps the existing fixed safe log. The final survey has the unchanged wire shape and
downstream `require_idle` remains authoritative. This is a bounded read-only retry,
not a Task attempt, budget refund, approval or proof of old execution stop.

## Validation matrix

| Observations | Result |
| --- | --- |
| typed incomplete → typed idle | return last complete idle |
| typed incomplete → typed active or unknown | return blocker immediately |
| typed incomplete × 3 | return final incomplete |
| parent/worker protocol or cleanup failure | synthetic incomplete, one attempt |
| typed incomplete plus active blocker | return both blockers, no retry |

## Tests

Run the focused red-capable facade tests, then the whole local survey and contained
UNKNOWN suite, Ruff, Mypy and `git diff --check`. No real production recovery is
performed from this worktree.

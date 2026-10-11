# Console idle dispatcher backoff

## Scope and signatures

`web_console/core.py.ProjectConsole._run() -> None` is the existing serial
Operation worker. `ProjectConsole(..., poll_seconds: float = 0.25)` keeps its
positive initial interval. This changes scheduling frequency only; existing
Operation wire, Schema, store, admission and controlled-stop contracts stay intact.

## Contract

- On consecutive idle claims, wait `poll_seconds`, `max(poll_seconds, 1.0)`,
  `max(poll_seconds, 2.0)`, then `max(poll_seconds, 5.0)` seconds repeatedly.
  Defaults are 0.25→1→2→5 seconds. A custom initial value remains a lower bound.
- A wake Event or executed Operation resets the delay. Existing same-process
  submit, begin_shutdown and cancel_shutdown continue to signal that Event.
  No real Operation waits for the next idle timer after a same-process submit.
- Clear a prior wake before each complete claim. A submission persisted before
  clearing is visible to that claim; one persisted afterward signals the wait.
  Never clear a fresh signal after a claim and before entering its wait.
- An external store writer has no in-process Event. Its authorized work is found
  on the next complete claim, after at most the default five-second idle wait
  plus actual store/worker scheduling time. No cross-process instant guarantee.
- Every actual `run_once` still calls the original `claim_next` under admission
  and store locks. Full bytes/hash/path/history and same-size/mtime tamper gates
  remain unchanged. Backoff cannot cache authorization, skip a claim check,
  create stop proof, turn a claim failure into idle, or change retries/verdicts.
- Shutdown still waits for actual dispatcher exit and terminal persistence;
  beginning shutdown wakes the longest idle wait immediately. Restarting a
  dispatcher starts a fresh initial delay.

## Validation matrix and required tests

| Case | Required result |
| --- | --- |
| Good: stable idle | Exact finite sequence, capped waits, no busy-spin |
| Base: external writer | Discovery next timer, original complete store verification |
| Bad: damaged historical byte/path | Fail closed through unchanged store gates |
| Same-process submission during max wait | No simulated timeout consumed; executed then delay reset |
| Wake with no queued work / idempotent replay | Delay reset without creating another execution |
| Success or rejected Operation | Existing terminal facts persisted; delay reset |
| Longest idle wait then shutdown/cancel | Immediate wake, existing readiness gates, initial delay on resume |

`tests/web_console/test_idle_backoff.py` drives the real worker with a bounded
fake Event; no five-second test sleeps. Keep `test_core.py`, `test_shutdown.py`
and `test_idle_replay.py` regressions, including complete-byte tamper rejection.

## Existing facts and rollback

No journal rewrite, SQL migration, new Requirement or audit modification is
needed. Load only during an idle controlled maintenance deployment. Reverting
the code restores the old cost while retaining every durable fact and draft.

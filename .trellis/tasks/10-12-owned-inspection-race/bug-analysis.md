# Bug analysis: disappearing Darwin process during birth inspection

## 1. Root cause category

**E — implicit assumption, D — missing boundary coverage.** The short BSD birth-query result was
treated as unknown whenever its errno was not ESRCH, without checking whether the kernel now
confirmed PID absence. Initial SID existence, birth readability and current PID existence occur
at different times. The exact public delivery fixture's original failure remains unproven.

## 2. Prior diagnostic limits

A diagnostic public rerun passed and neither real command/save nor bounded process-churn probes
reproduced the original error. The durable failure stored only the wrapper class name, so those
facts cannot establish whether the original first error was a birth query, another inspection
failure or another owned runner. No guessed historical reason or stop record was written.

## 3. Prevention mechanisms

| Priority | Mechanism | State |
| --- | --- | --- |
| P0 | Fresh kernel ESRCH only after a short birth query; living/recycled/denied stays unknown | Implemented |
| P0 | Deterministic zero/positive-partial result, no errno/ENOENT, live SID and denial tests | Implemented |
| P0 | Existing complete session/known birth/EOF/durable-save gates and actual child tests | Retained and incrementally verified |
| P1 | Preserve a safe typed first-reason code through owned runner and delivery checkpoint wrappers | Separate follow-up proposal; outside this fix |

## 4. Systematic expansion

The same inspector supplies controller capture, current session reads, individual signal checks and
recorded-proof validation. Therefore one narrow absence rule reaches each consumer without changing
its permissions or proof. Complete enumeration, birth drift, escapes, capture-after-reap and save
failures still reject. Linux uses its existing `/proc` absence contract and is unchanged.

For the separate diagnostics proposal, use a fixed typed reason such as birth unavailable, session
identity drift, output EOF unknown or record save unconfirmed; map it to fixed Chinese guidance.
Do not expose raw exceptions/provider text or retain Exception/traceback payloads in long-lived
ownership capabilities. Recording the first safe reason must preserve checkpoint history and
remain distinct from declaring a process alive or accepting a role verdict.

## 5. Knowledge capture and existing data

The executable signatures, fresh-ESRCH contract and validation matrix are recorded in
`.trellis/spec/core/owned-session-stop.md`. No template tree exists in this repository. No Schema,
canonical bytes, MySQL facts, historical proof, Task, approval or queue identity was changed. Root
must separately integrate, run its serial public fixture and deploy at an idle controlled boundary.

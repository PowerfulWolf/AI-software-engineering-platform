# Memory incident measurements

2026-10-06, local read-only probes. PID 80012 physical footprint rose from 6.9 to 9.0 GiB, while RSS was about 1.1–1.7 GiB; vmmap recorded ~5.5 GiB swapped ownership at the first sample. Approximately five threads. No queued/running Console Operation was returned by the public operations endpoint immediately before a trusted idle restart. Numeric probes and native function-only sample are outside the repository in the maintenance directory; no heap content or secrets were collected.

Trusted idle restart replaced PID 80012 with 84247. New-process early physical footprint samples were 1.5 then 1.9 GiB. Restart is pressure mitigation, not a repair or evidence against a leak.

Ranked falsifiable hypotheses: (1) overlapping uncancellable Team reads amplify peak; admission of a second read while the first remains active must fail after a gate repair. (2) full journal histories plus private validated cache/deep copies cause excessive single-read amplification; serial filesystem replay must show the current/peak attributable to each stage and bounded release. (3) completed read/operation/background objects remain strongly referenced; retained traced memory must increase after repeated reads and GC if true. (4) allocator retention explains footprint after transient release; traced current returns near baseline while physical footprint plateaus if true.

## Confirmed cause and repair

Real filesystem replay through retirement, complete journal histories/native membership and Project summaries retained approximately 449 MB per completed read. Minimization to a 34-record historical unstarted-design correction showed a validator traceback retained by Pydantic native error context, linking back to completed history/caller frames. Cold/warm largest-journal reads and single-checkpoint decode did not grow. Cloning safe outer errors and clearing only the top traceback were negative controls. Detaching only nested `ctx.error` exception execution references changed the real replay from red to green without weakening validation.

Final unpatched three-round replay: released traced memory 259110 / 267748 / 273649 bytes; all Journal/cache weak references released, 0 SQL calls, original source inventory unchanged. Physical footprint after release 0.257 / 0.417 / 0.414 GiB. No forced-GC loop is part of production code. Native/joint caller-lifetime regressions failed twice on old code and passed after repair; an independent reviewer reproduced both outcomes.

Public Console concurrent/cancelled caller red tests showed second reads entering on old code. Repaired app-local worker gate rejects overlapping reads and stays held through reader, wire conversion and JSON rendering. Safe and unexpected errors release it. This bounds simultaneous read peaks and is distinct from the actual serial retention repair.

Incremental verification: 74 selected Python tests across memory, admission/correction/journal, production Agents, transport and Console core passed. Ruff and changed-file Mypy (`--follow-imports=silent`) pass; importing unrelated helper-test implementations into full Mypy traversal exposes 23 existing errors, not new runtime errors. No full test suite was run.

While idle, the trusted script restarted PID80012 as84247 for pressure mitigation; repeated footprint still climbed1.5→1.9→4.6→6.0GiB. After a second public check showed0activeOperations, the trusted service was stopped pending deployment to avoid further pressure. No delivery commands or approvals were submitted. User subsequently requested layout improvement and explicitly reserved all further ASE delivery decisions/actions for them; that boundary is now in force.

## Production repair validation

Repair commit `09edc12` was pushed and fast-forwarded into the production checkout. The trusted
service script loaded the repair as PID 94152. Six samples at ten-second intervals recorded physical
footprint 0.3292 / 0.3396 / 0.3418 / 0.3428 / 0.3407 / 0.3428 GiB (RSS 1108.89–1122.89 MiB).
The short repeated polling window passed the numeric gate and showed a plateau; this is not proof
against every possible long-running workload. Raw numeric facts are preserved in the external
maintenance directory. A validated current Team snapshot was captured for read-only delivery
diagnosis and isolated layout inspection. No delivery command, engineering investigation, approval
or resume was submitted. Existing SQL/journal/Task facts require no migration.

After the layout/diagnosis work, a further three ten-second-interval samples of the same PID were
0.6660 / 0.6484 / 0.6453 GiB physical footprint (RSS 1227.39–1238.42 MiB). These later samples remained
below the 2 GiB diagnostic gate and plateaued instead of the previous rapid multi-GiB growth. The
physical allocator/working set and RSS are distinct measurements; single-read transient peaks and
other future workloads still need observation. No additional service restart was needed.

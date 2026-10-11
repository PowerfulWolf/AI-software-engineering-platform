# Primary-source investigation

Initial static study used `8c7cafa4a11617ec3e32169549233919dd4ee99a`; implementation is based on
`60512345ebcb15986a93e1458ffec554e59a139d`. Root supplied run7's production facts; this agent
performed no production process, file or database read. An independent research agent traced
legacy/source/queue gates without edits. Root later explicitly authorized the implementation.

The existing routes cannot admit the described facts by relabelling them:

| Owning source | Existing contract | Consequence |
| --- | --- | --- |
| `agents/codex_cli.py:853` | `finished` runs before `output_path.read_text`, within TemporaryDirectory | An inventory refusal removes the unparsed temporary output on scope exit; existence cannot reconstruct bytes |
| `manager/rejected_output_checkpoint.py:47` | SUCCEEDED CoderProgressArtifact with exact sequence mismatch only | FAILED/noartifact cannot be declared a rejected progress artifact |
| `manager/wait_fact_collection.py:139` | Existing outcome returns early except supported rejected progress | Capturing the completed/noartifact case needs a distinct baseline capability |
| `orchestration/capture_reconciliation.py:114` | Real cause/code required and output must be absent | Completed return0/output-present cannot become an interruption receipt |
| `orchestration/continuation_models.py:111` | TIMEOUT requires actual local limit; transient cause requires failed native stop | Do not invent TIMEOUT/provider cause or refund |
| `manager/baseline_production.py` (`_reservation`) | Only interruption/transient/legacy/uninvoked original reservations | Add a separately typed normal-work cause |
| `manager/baseline_production.py` (`_legacy_containment`) | Rejects existing outcome and capture-start/stop ledger | Deleting/ignoring facts to qualify as legacy rescue is forbidden |
| `manager/baseline_models.py` (`ExecutionBaselinePlan.validate_plan`) | Ordinary SOURCE_REBIND requires a different target base | Existing source-update purpose is sufficient for root's approved newer target; same-base rescue remains outside scope |
| `work_queue/baseline.py` (`consume_baseline`) | Non-provider reservations charge ordinary frozen work | Reuse this branch; no queue/state-machine expansion is necessary |
| `work_queue/baseline.py` (`release_baseline_pause`) | Exact full saved plan/consumption and current source/inventory are revalidated | Reuse PAUSE/explicit latest-bound RESUME |

`git/mutation.py` observes ignored files, twice, without following symlinks. Its per-file bound is
16,000,000 bytes and its explicit cache capability includes Python bytecode, pytest and Ruff;
it does not include mypy. A reported 22 MB mypy file can fail that observation, but the old generic
WORK_INTERRUPTED outcome does not durably establish that diagnosis. Cache prevention/maintenance
and source recovery authority are separate tasks. No cache bound/allowlist change is included.

The reusable trusted seam is `validate_capture_stop` in `orchestration/capture_reconciliation.py`:
it binds original Task attempt/intent/policy/revision, exact scope/request/historical claim and
start/stop digest, holds the real Task lock and rechecks the original PGID. It proves stopping,
not output content or workspace readiness. The independent native-session coverage note documents
its narrower PGID/EOF scope; that proof is neither strengthened nor reinterpreted here.

The public regression uses `tests/manager/test_production_execution_baseline.py` and the actual
TeamHost proposal/execute/continue interfaces. Its real owned runner, immutable invocation journal,
fenced MySQL queue, new claims and independent role fixtures establish the final chain. Focused
tests supplement scope/lease/output/stop/workspace negatives. The canonical Schema owner is
`scripts/sync-legacy-rescue-schemas.py::guards`; both embedded and final standalone writeback must
apply its gates, or standalone regeneration erases them.

Root review identified a retained-history edge: `MySqlRoleQueue.accepted(task)` retains raw old
publication receipts after an exact rejected-output decision has consumed them. At a reused queue
checkpoint, only `rejected_output_artifact_ids(task)` may exclude the exact old ID; current-work
publication and unconsumed/ancestor IDs still reject. Root independently owns any production
receipt inspection. The final Plan also validates its inventory/body fingerprints purely when
decoded, while runtime authorization uses the live complete workspace.

Existing-data recovery is public source proposal → inspect full captures/facts → approve exact
plan with PAUSE → explicitly RESUME. Root separately preserves/audits target caches. Keep original
FAILED/noartifact/stop/output-present facts, frozen budget and all old histories. A terminal Task,
unknown current stop, incomplete/unauthorized draft or exhausted work budget remains ineligible.

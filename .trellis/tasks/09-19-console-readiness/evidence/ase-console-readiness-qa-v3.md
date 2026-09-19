# Independent Console readiness QA — In-flight submission recovery

- task_id: `console-readiness`
- source_revision: `b8983b82fbc56c6b7d90dbc0c2722af835bee614`
- context_manifest_id: `console-readiness-20260919`
- QA agent: `/root/console_qa`
- workspace: `/private/tmp/ase-console-readiness-20260919`
- conclusion: **PASS for the tested frontend regression scope**
- candidate identity: uncommitted worktree patch, bound to final app.js SHA-256 below.
- prior reports retained: `/private/tmp/ase-console-readiness-qa.md` and
  `/private/tmp/ase-console-readiness-qa-v2.md`.

This report supersedes the previous candidate identities and test counts. It is an engineering QA
report, not a runtime Artifact or state-machine transition approval. QA only extended the independent
test harness and wrote this report; all production changes were made by the implementer.

## Review finding and independent reproduction

Reviewer found a disabled-state recovery race: a pending Project POST made submit busy; simultaneous
Team and Operations GET failures cached that disabled value; the POST then failed while reads were
still unavailable; restored reads replayed the stale busy value and left the same form permanently
disabled although `canControlCurrentTeam()` was true.

QA added a deferred Project POST response to the HTTP fixture and two tests that keep the actual
form and input nodes throughout the failure/recovery sequence:

1. Start Project POST; fail Team and Operations reads; reject the POST; restore reads. The submit
   button must stay gated until reads recover, then become enabled for retry. The entered name and
   exact form node must survive, and the failed POST must show feedback.
2. Start Project POST; fail reads; restore reads while the POST is still pending. Connectivity alone
   must not clear the busy state. Reject the POST afterward; only then may submit become enabled.

Before the production fix, the same expanded readiness test file was executed against
`/private/tmp/ase-console-readiness-before-busy-fix.js`, the exact previous candidate with SHA-256
`bc4fe19f76951dfc265b3ebc96d0c863208f71f5bc8b7885f2c193505b710257`.
Result: **17 passed / 1 failed**. The first new test failed exactly at:
`completed POST failure and restored connectivity must allow retry` (`true !== false`).
The inverse-order test and all 16 previous readiness tests passed.

Both orderings now pass against the final script. No test assertion was weakened to accept a stale
disabled button, premature enabling, recreated form, or discarded draft.

## Commands and results

| Command | Result |
| --- | --- |
| `node --check src/ai_software_engineer/team_view/app.js` | exit 0 |
| `node --check tests/team_view/readiness.test.cjs` | exit 0 |
| `node --test tests/team_view/*.test.cjs` | exit 0; **24/24 passed**, none skipped |
| `git diff --check` | exit 0 |
| `ASE_READINESS_APP_JS=/private/tmp/ase-console-readiness-before-busy-fix.js node --test tests/team_view/readiness.test.cjs` | expected exit 1; **17 passed / 1 failed** |

The final suite includes 18 independent readiness tests and 6 existing UI tests. Earlier task-baseline
and pre-Review-fix red evidence remains available with the retained v1/v2 reports.

## Final evidence identities

| File | SHA-256 |
| --- | --- |
| `src/ai_software_engineer/team_view/app.js` | `a20ba889600ee7918f1e6d66ccd7389feed46d145fe515bbcb3a87184ce7f8c6` |
| `tests/team_view/readiness.test.cjs` | `107d6d6cb81a6bd8f1d0682a16e143e826bdaeccafc0c6c5fd64cb5b1109a759` |
| `/private/tmp/ase-console-readiness-qa-v3-tests.log` | `24879541e575a2feae80adf1be9599a73426e4e97839ff9623759ccad36384f8` |
| `/private/tmp/ase-console-readiness-before-busy-fix-tests.log` | `21947e86c2a063c327456ad25931988533bf15a644ab02b181ca4ecf5fdd1c84` |

## Limits and persisted-data handling

No remaining blocker was found in the tested scope. This is deterministic Node VM/DOM validation,
including actual asynchronous application handlers with fake deferred HTTP and controlled timers;
it does not claim real-browser visual, focus/caret, deployment, or production-restart acceptance.
Independent Reviewer recheck remains required. QA did not modify production code/specifications,
call a production model, or write production database/Operation/approval/queue facts.

The fix changes transient browser busy/gate state. No persisted facts require repair or migration;
existing history is retained. Deploy the verified asset and reload the browser to read current runtime
facts. Rollback is restoration of the frontend patch and does not require data changes.

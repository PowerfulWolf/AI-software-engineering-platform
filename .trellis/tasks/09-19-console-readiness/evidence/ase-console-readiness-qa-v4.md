# Independent Console readiness QA — Requests confirmation recovery

- task_id: `console-readiness`
- source_revision: `b8983b82fbc56c6b7d90dbc0c2722af835bee614`
- context_manifest_id: `console-readiness-20260919`
- QA agent: `/root/console_qa`
- workspace: `/private/tmp/ase-console-readiness-20260919`
- conclusion: **PASS for the tested frontend regression scope**
- candidate identity: uncommitted worktree patch, bound to final app.js SHA-256 below.
- prior QA reports v1, v2, and v3 are retained at their original `/private/tmp/` paths.

This report supersedes earlier candidate identities and test counts. It is an independent engineering
QA report, not a runtime Artifact or state-machine transition approval. QA changed only the test file
and this report; the implementer made the production fix.

## Review finding and reproduction

Reviewer identified another consumer of the same busy/gate lifecycle: a Requests confirmation's
proceed button. Its direct disabled assignments left a stale busy value cached if its operation failed
while Team/Operations reads were unavailable; reconnecting could leave the existing confirmation
permanently disabled.

The new regression uses a realistic READY_FOR_DISCUSSION Requirement, opens its actual detail
“删除需求” action, clicks the actual “确认删除” button, and defers the resulting Operation POST.
It then fails Team and Operations GETs, rejects the POST, and restores both reads. Assertions require:

- exactly one Operation POST was initiated;
- the confirmation remains disabled during the in-flight operation and while the read gate is closed;
- after POST failure and reconnect, `canControlCurrentTeam()` is true and the same proceed control
  becomes enabled for retry;
- the exact confirmation dialog node is retained and the failed operation's feedback remains visible.

The test does not substitute a synthetic confirmation action: it exercises the production Requirement
delete callback and `submitOperation` failure route.

Before the fix, the exact previous app.js was frozen at
`/private/tmp/ase-console-readiness-before-confirmation-fix.js`, SHA-256
`a20ba889600ee7918f1e6d66ccd7389feed46d145fe515bbcb3a87184ce7f8c6`.
The expanded readiness suite against that script yields **18 passed / 1 failed**, precisely at
`a completed failed confirmation must become retryable after reconnect` (`true !== false`).
The fixed candidate passes that assertion and the additional closed-gate assertion.

## Commands and results

| Command | Result |
| --- | --- |
| `node --check src/ai_software_engineer/team_view/app.js` | exit 0 |
| `node --check tests/team_view/readiness.test.cjs` | exit 0 |
| `node --test tests/team_view/*.test.cjs` | exit 0; **25/25 passed**, none skipped |
| `git diff --check` | exit 0 |
| `ASE_READINESS_APP_JS=/private/tmp/ase-console-readiness-before-confirmation-fix.js node --test tests/team_view/readiness.test.cjs` | expected exit 1; **18 passed / 1 failed** |

The final suite comprises 19 independent readiness tests and 6 existing UI tests. Earlier red/green
comparisons remain recorded in the preserved v1–v3 QA reports and logs.

## Final evidence identities

| File | SHA-256 |
| --- | --- |
| `src/ai_software_engineer/team_view/app.js` | `bbebc6578d4f89921ba82a46af93d5e31cef35abf7fad843e42e5e1a49c824be` |
| `tests/team_view/readiness.test.cjs` | `100dcfe9ab6b2a109182ed81a62c927bc84e3281a9e176c5a1aadf40e31e1793` |
| `/private/tmp/ase-console-readiness-qa-v4-tests.log` | `5fcff90724fc2109ef5c89eae421461bb1828f17527cfdc9023453a2d6f47b28` |
| `/private/tmp/ase-console-readiness-before-confirmation-fix-tests.log` | `3c86169aedf5e25ac9aeabcfb1a16682827ef7b0025074c18a01e4048611742c` |

## Limits and persisted-data handling

No remaining blocker was found within this tested scope. Tests execute the actual app.js in a Node
VM/DOM harness with controlled timers and deferred fake HTTP. This report does not claim browser
visual/focus/caret acceptance, real deployment or process restart validation, or universal race coverage.
Independent Reviewer recheck remains required. QA did not change production code/specifications,
call production models, or modify production database/Operation/approval/queue facts.

No persisted facts need repair: the change concerns transient browser notifications and control state.
Existing histories remain intact. After deployment, reload the browser to load the verified script and
current runtime facts. Rollback requires reverting the frontend patch; there is no data migration.

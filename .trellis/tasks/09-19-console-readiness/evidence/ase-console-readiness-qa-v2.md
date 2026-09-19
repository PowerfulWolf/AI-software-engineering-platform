# Independent Console readiness QA — Review follow-up

- task_id: `console-readiness`
- source_revision: `b8983b82fbc56c6b7d90dbc0c2722af835bee614`
- context_manifest_id: `console-readiness-20260919`
- QA agent: `/root/console_qa`
- workspace: `/private/tmp/ase-console-readiness-20260919`
- conclusion: **PASS for the tested frontend regression scope**
- candidate identity: uncommitted worktree patch, bound to the final app.js SHA-256 below.
- prior report retained at `/private/tmp/ase-console-readiness-qa.md`.

This report supersedes the prior report's candidate identity and test counts. It is an engineering QA
report, not a runtime Artifact or state-machine transition approval. QA only extended
`tests/team_view/readiness.test.cjs` and wrote this report; the implementer made all production fixes.

## Review findings and regression evidence

Reviewer identified two additional issues after the first QA round:

1. A success-expiry timer could render another page, rebuilding an unrelated new Project form or
   confirmation modal and discarding DOM-held draft values.
2. Concurrent Team and Operations read failures could leave old delivery controls active; invoking
   the submission function could still issue an Operation POST despite an unavailable control gate.

Before fixes, QA copied the prior candidate app.js to
`/private/tmp/ase-console-readiness-before-review-fixes.js`, SHA-256
`a1496d6bb47d510b3d95d55b7d6ab61a14ef18139e872705008908edda415c42`.
The expanded tests run against that exact script produce **11 passes and 5 expected failures**:

- expiry must retain the exact new Project input node and entered name;
- expiry must retain the exact unrelated confirmation dialog node;
- simultaneous failures must hide the existing Project creator, disable the existing Requirement
  submit button, retain input node/value, and restore controls without rebuilding the form on recovery;
- directly invoking `submitOperation` while unavailable must issue **zero** `/api/v1/operations` POSTs;
- an existing Project form must issue **zero** `/api/v1/admin/projects` POSTs while unavailable,
  retain its node/draft, and restore the submit button on recovery.

The final candidate passes all five, plus the original 11 readiness regressions and 6 existing UI
tests. The simultaneous-failure test additionally verifies that the operation-records unavailable
message appears and disappears correctly while the existing form survives.

The small DOM harness now supports attribute selectors and reads data attributes from both
`setAttribute` storage and `dataset`, matching the relevant browser behavior. No production behavior
was bypassed or mocked out: tests execute the actual app.js and its navigation/timer/submit handlers.

## Commands and results

Commands ran in the workspace above.

| Command | Result |
| --- | --- |
| `node --check src/ai_software_engineer/team_view/app.js` | exit 0 |
| `node --check tests/team_view/readiness.test.cjs` | exit 0 |
| `node --test tests/team_view/*.test.cjs` | exit 0; **22/22 passed**, none skipped |
| `git diff --check` | exit 0 |
| `ASE_READINESS_APP_JS=/private/tmp/ase-console-readiness-before-review-fixes.js node --test tests/team_view/readiness.test.cjs` | expected exit 1; **11 passed / 5 failed** |

The original task baseline red comparison remains recorded in the first QA report and
`/private/tmp/ase-console-readiness-baseline-tests.log`; this follow-up specifically isolates the
additional Review findings against the previously tested candidate.

## Final evidence identities

| File | SHA-256 |
| --- | --- |
| `src/ai_software_engineer/team_view/app.js` | `bc4fe19f76951dfc265b3ebc96d0c863208f71f5bc8b7885f2c193505b710257` |
| `tests/team_view/readiness.test.cjs` | `fc32b501eadf33e4f099366ede060b78440fec8ebee57e6b98ae3982971f2ca5` |
| `/private/tmp/ase-console-readiness-qa-v2-tests.log` | `4e782782d24cb6ad0fc0fc03d9f4de87deaf66214ee226d14709d98434d5c44b` |
| `/private/tmp/ase-console-readiness-before-review-fixes-tests.log` | `d43bfa5b40ec1388e4194fccb57c2959c9bf51ab2eb02cb5f7410b097b58c8c2` |

## Limits and persisted-data handling

No remaining blocker was found in the tested scope. Independent Reviewer recheck is required before
delivery. These are deterministic Node VM/DOM regressions with fake HTTP and controlled timers, not
real browser visual, focus/caret, deployment, or production restart acceptance. QA did not call a
production model, write production data, or modify approval/Operation/queue facts.

No persisted facts require repair for these frontend bugs. Existing apply lifecycle history is
retained. After deployment, reload the browser page to obtain the verified script and current
Console/Settings/Status facts. Rollback is restoration of the prior frontend patch; no migration is
introduced by this change.

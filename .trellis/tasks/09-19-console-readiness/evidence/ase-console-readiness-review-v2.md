# Independent Console readiness Review — v2

- task_id: `console-readiness`
- source_revision: `b8983b82fbc56c6b7d90dbc0c2722af835bee614`
- context_manifest_id: `console-readiness-20260919`
- Reviewer: `/root/console_review`, independent from Coder and QA
- Workspace: `/private/tmp/ase-console-readiness-20260919`
- Candidate app.js SHA-256: `bc4fe19f76951dfc265b3ebc96d0c863208f71f5bc8b7885f2c193505b710257`
- Scope: recheck the two prior findings and their local timer/control-gating fixes only.
- Conclusion: **Both prior reproductions fixed; one medium-severity recovery blocker remains in the new control-suspension logic.**

This is a read-only engineering review, not a platform Task verdict. The prior report at
`/private/tmp/ase-console-readiness-review.md` remains unchanged. No candidate file or persisted
business fact was modified by Reviewer.

## Findings

- Severity: medium
- File: `src/ai_software_engineer/team_view/app.js:244`
- Issue: `suspendedDeliveryControls` captures the old disabled flag once and restores it even if the
  underlying submission has finished. Start a Project POST (button becomes disabled), lose Team and
  Operations reads while the POST is pending (the WeakMap captures true), let the POST fail while
  disconnected (the catch sets disabled=false but `syncDeliveryControls` keeps the cached true), then
  restore the read endpoints. `canControlCurrentTeam()` becomes true, yet the preserved form's submit
  remains permanently disabled. Existing modal-preservation logic prevents a fresh render from fixing
  it. The operator must discard/reopen the form to retry. This is a direct regression of the new
  gate suspension/restoration, and can also affect other submit controls that change disabled state
  while suspended.
- Recommendation: Track the operation's busy/disabled state separately from the connection gate, or
  update the suspended underlying disabled value whenever the operation completes/fails. Apply the
  same rule to affected delivery submit controls. Add a deferred POST regression covering read loss,
  POST failure, and read recovery; the exact draft/form must remain and submit must become enabled.

## Recheck evidence

- Independently reran `node --test tests/team_view/*.test.cjs`: exit 0; **22/22 passed**.
- `git diff --check`: exit 0.
- Inspected the exact incremental diff from the previous candidate at
  `/private/tmp/ase-console-readiness-before-review-fixes.js`.
- The success timer now renders only Settings, fixing the reported cross-page modal reset.
- In-place control gating and the Operation/Project submission checks fix the reported simultaneous
  Team+Operations failure case. The five new QA regressions cover the original reproductions.
- A further read-only Node VM probe loaded the existing QA harness and exact candidate. Its Project
  POST was held on a deferred promise; Team+Operations were made unavailable, then the POST rejected,
  then both read endpoints recovered. Observed output:

```text
after POST+read failures recover: canControl= true submit.disabled= true sameForm= true
```

This probe used fake HTTP and DOM only. No production service, model, database, Operation journal,
approval, or queue was touched. The limitation is local to the control-gating repair; no unrelated
review scope or full-suite testing was introduced.

| File | SHA-256 |
| --- | --- |
| `src/ai_software_engineer/team_view/app.js` | `bc4fe19f76951dfc265b3ebc96d0c863208f71f5bc8b7885f2c193505b710257` |
| `tests/team_view/readiness.test.cjs` | `fc32b501eadf33e4f099366ede060b78440fec8ebee57e6b98ae3982971f2ca5` |
| `.trellis/spec/core/web-console.md` | `4a8f2b484b3b908fc8a55d99d7d0391d4bc3aa25a186f3115f86a7ad67e1b930` |
| `/private/tmp/ase-console-readiness-qa-v2.md` | `fa9d7d1875705fbf128b0e1f1c253398e8ec3bc0ae4317fc62166c211af9e92f` |

No persisted-data repair is required. Return only this local recovery issue for implementation and
QA, then re-review the updated hash. Reviewer does not merge or approve runtime state transitions.

# Independent Console readiness Review

- task_id: `console-readiness`
- source_revision: `b8983b82fbc56c6b7d90dbc0c2722af835bee614`
- context_manifest_id: `console-readiness-20260919`
- Reviewer: `/root/console_review`, independent from Coder and QA
- Workspace: `/private/tmp/ase-console-readiness-20260919`
- Candidate: uncommitted patch, app.js SHA-256 `a1496d6bb47d510b3d95d55b7d6ab61a14ef18139e872705008908edda415c42`
- Conclusion: **Two medium-severity blockers; return to implementation before delivery.**

This is a read-only engineering review, not a platform Task verdict. Reviewer changed no candidate
code, tests, specs, Git metadata, database, model execution, or durable delivery facts.

## Findings

- Severity: medium
- File: `src/ai_software_engineer/team_view/app.js:2311`
- Issue: The new success-expiry timer calls the global `render()` after five seconds regardless of the
  active page or modal. If the user leaves Settings after successful apply and starts creating a
  Project/Requirement or editing knowledge before that timer fires, `renderComposer()` reconstructs
  the modal from its initial state and discards unsaved DOM-only fields. This bypasses the existing
  modal-preservation guard in `refresh()`. Independently reproduced with the shipped script and QA DOM
  harness: apply successfully, navigate to Requests, open the Project composer, type a name, fire the
  5000 ms timer; the name changes from `Unsaved project draft` to the empty string.
- Recommendation: Expire the success state without rebuilding unrelated pages or composers. Refresh
  only the affected Settings notice/dialog, or preserve active drafts during that render. Add a
  regression that navigates away after apply, starts editing a Project/Requirement, and expires the
  success notification without losing entered values.

- Severity: medium
- File: `src/ai_software_engineer/team_view/app.js:5127`
- Issue: The new independent system reads can invalidate `operationsAvailable` while a Team read also
  fails, but the catch branch only rerenders Settings/Status. On Requests, already-rendered delivery
  controls remain available even though `canControlCurrentTeam()` is now false. Existing event
  handlers call `submitOperation()` without rechecking that gate, so a stale Continue/Approve action
  can still submit despite unavailable Operation facts. Independently reproduced after a successful
  Requests render: make both Team and Operations reads fail, poll, and observe `canControl=false`
  while `project-creator.hidden=false`. This violates the patch's explicit contract that unavailable
  Operations disable delivery commands.
- Recommendation: Update/disable Requests controls when system authority changes even if Team refresh
  fails, preserving any modal draft, and check current authority at the operation submission boundary.
  Add a combined Team+Operations failure regression covering an existing rendered action and an open
  composer; assert no POST is sent until the authority recovers.

## Evidence

- `node --test tests/team_view/*.test.cjs`: independently rerun; exit 0, 17 passed, 0 failed.
- `git diff --check`: exit 0.
- Reviewed actual apply lifecycle, render/composer, refresh, navigation and operation paths against
  task PRD/design and applicable Web Console / live Team read-side contracts. Spec changes correctly
  document the intended readiness and notification behavior; no mirrored template exists here.
- Independent Node VM probe loaded the existing QA harness prefix (before test registration), executed
  the exact candidate script, then exercised the two sequences described above. Output:

```text
draft before success timer: Unsaved project draft
draft after success timer:
combined read failure: canControl = false creator hidden = false
```

The probe used fake HTTP/DOM/timers only, with no repository changes, production model, or database.
The three reported original symptoms are covered by passing regression tests, but the two regressions
above prevent accepting the current candidate.

| File | SHA-256 |
| --- | --- |
| `src/ai_software_engineer/team_view/app.js` | `a1496d6bb47d510b3d95d55b7d6ab61a14ef18139e872705008908edda415c42` |
| `tests/team_view/readiness.test.cjs` | `c41cf36831a5f64efd4043275276f8103234c4a3f5f616052ab805448bd0e0fd` |
| `.trellis/spec/core/web-console.md` | `f66b550028dbacf4dad74cba8e739068bc17f45b2205938c3fb29435cf7c3d08` |
| `.trellis/tasks/09-19-console-readiness/prd.md` | `b7e69418c48ab81fc71313a571a7b278bfb594f687a3f35c78773c968d483bef` |
| `.trellis/tasks/09-19-console-readiness/design.md` | `c09cfe653e10fe2131068abfc7c4bad1cf4a6ef87d7afb64119b53e555aaf4a1` |
| `/private/tmp/ase-console-readiness-qa.md` | `a520f74772f48f465b40545beb77d9ef6271c023c1ed20cfc3782f890d034305` |

No persisted-data repair or business-state rewrite is required. Apply the targeted fixes, have QA
exercise the new cases, and re-review the updated candidate hash. Reviewer does not merge.

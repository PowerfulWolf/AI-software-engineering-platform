# Independent Console readiness Review — final v3

- task_id: `console-readiness`
- source_revision: `b8983b82fbc56c6b7d90dbc0c2722af835bee614`
- context_manifest_id: `console-readiness-20260919`
- Reviewer: `/root/console_review`, independent from Coder and QA
- Workspace: `/private/tmp/ase-console-readiness-20260919`
- Candidate app.js SHA-256: `bbebc6578d4f89921ba82a46af93d5e31cef35abf7fad843e42e5e1a49c824be`
- Conclusion: **No remaining blocking findings in the reviewed frontend scope.**

This is an independent engineering review, not a platform Task verdict or merge authorization.
Reviewer changed no code, tests, specifications, Git metadata, database, Operation, approval or queue.
Earlier Review reports remain intact at `/private/tmp/ase-console-readiness-review.md` and
`/private/tmp/ase-console-readiness-review-v2.md`.

## Findings

No remaining issues found in this scoped re-review. All previously reported blocking reproductions
are resolved on the exact candidate SHA above.

## Evidence and resolution

- Independently reran `node --test tests/team_view/*.test.cjs`: exit 0, **25/25 passed**, no skips.
  This includes 19 independent readiness regressions and 6 existing UI tests.
- `git diff --check`: exit 0.
- Read final independent QA report `/private/tmp/ase-console-readiness-qa-v4.md` and verified its
  candidate/test identities. QA preserved red comparisons against the exact preceding candidates.
- Success expiration only rerenders Settings. The actual cross-page Project input and unrelated
  confirmation dialog survive expiration without replacement; historical success is not replayed.
- Console/Settings facts refresh independently of Team projection, including an absent initial
  snapshot. Operation read failure keeps runtime facts distinct while revoking delivery controls.
  In-place updates preserve editable drafts, and Operation/Project submission recheck the gate.
- Reviewed `setDeliveryControlDisabled` and every marked delivery control's business-disabled
  mutation. Project, Requirement, Product reply and Requests confirmation paths all synchronize the
  latest busy state with suspension. Unrelated Knowledge confirmations keep their existing semantics.
- Deferred Project POST tests cover both relevant orders: POST failure before read recovery, and read
  recovery before POST failure. They preserve the exact form/draft, remain disabled while required,
  and permit retry after both the request and gate settle.
- During this review, the Requests confirmation proceed button was found to be the remaining missed
  consumer on intermediate SHA `a20ba889600ee7918f1e6d66ccd7389feed46d145fe515bbcb3a87184ce7f8c6`.
  Implementer connected both its busy transitions to the helper. The final regression exercises the
  actual Requirement delete confirmation, deferred Operation POST failure and read recovery, retaining
  the exact dialog/control and enabling retry. The previous candidate fails this assertion.
- Owning `.trellis/spec/core/web-console.md` documents bounded feedback, readiness authorities,
  missing-Team rendering, draft preservation, gate checks, and both busy/reconnect orderings. No
  mirrored template or Schema change is needed for these browser-only facts.

## File identities

| File | SHA-256 |
| --- | --- |
| `src/ai_software_engineer/team_view/app.js` | `bbebc6578d4f89921ba82a46af93d5e31cef35abf7fad843e42e5e1a49c824be` |
| `tests/team_view/readiness.test.cjs` | `100dcfe9ab6b2a109182ed81a62c927bc84e3281a9e176c5a1aadf40e31e1793` |
| `.trellis/spec/core/web-console.md` | `b10e8c43f04b3fac25f9cbbd79c9245d61ba3c9d5050f83791d2176cc5126709` |
| `/private/tmp/ase-console-readiness-qa-v4.md` | `6b071a44e5cd43c7c6125f800e424c366b4436e019813bdefc76325f540cad6c` |

## Limits and existing-data disposition

Review and tests use actual app.js with controlled DOM/HTTP/timers; they do not claim browser visual,
focus/caret, deployment, or real restart acceptance. Scope is the reported readiness/notification
repair and its directly related control-recovery changes, not unrelated repository behavior.

No persisted data needs repair. Existing configuration lifecycle, Requirements, Tasks, Operations,
approvals and queues retain their histories. After shipping this asset, reload the browser to obtain
the fixed script and reread runtime facts; a previously successful configuration restart does not need
repeating solely for these UI symptoms. Rollback restores the preceding frontend patch, without a
migration or business-state rewrite.

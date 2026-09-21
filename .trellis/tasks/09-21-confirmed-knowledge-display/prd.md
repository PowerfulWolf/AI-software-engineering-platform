# Confirmed knowledge display correction

## Scope and acceptance

- Show the persisted answer and source when expanding an answered/approved question.
- Use `已确认的知识` for the confirmed section/card state and `查看已确认的知识` for its entry.
  Keep `待继续` in the Requirement presentation: confirmation still does not resume delivery.
- If the detail GET sees approval before the Team snapshot, immediately update the section
  and current request guidance without closing the expanded answer or issuing another GET.
- Preserve answer line breaks; render as safe text, not HTML. Pending unsaved drafts are not
  confirmed knowledge, and a new current gap must remain pending.
- Late responses for a different checkpoint must not change its current state or cache.

Allowed paths: team_view/app.js and style.css, corresponding DOM tests, operator/spec docs,
this task and index. No backend/schema/workflow changes, real approval/resume, model calls,
or production data edits. Follow-up to e4552eb; rollback is a normal revert without migration.

## Checks

Add red/green DOM regressions for stale pending -> confirmed GET, matching snapshot reload,
same-checkpoint polling, multiline echo and isolation of a new gap. Run all Node UI tests,
focused persisted query regression, Ruff/Mypy, diff check and build. Verify served assets
match the checkout; this static-only correction does not require a service restart.

# Basic settings grouping and retry policy scope

## Goal and scope

Fix the reported lack of visible module separators and excessive vertical spacing in Basic settings.
The user explicitly approved implementing all-role retry configuration in this task. Separate typed
transient model failures from work/correction allowances, respecting each stage's semantics and
existing exact approval/recovery gates.

## Acceptance

- Related fields form named modules with visible separators, including the config-file metadata.
- Retry heading, description and fields have compact, consistent spacing on desktop and narrow screens.
- Keep the same editable draft, atomic save, input validation and restart behavior.
- Expose effective limits across model roles, distinguish discussion/correction/Coder iterations,
  and explicitly show Manager's deterministic (non-model) scope.
- Preserve existing Design configuration, journals, attempt facts and terminal recovery approvals.
- Browser regression asserts actual CSS geometry and borders, not only text presence.

## Implementation and validation

Allowed writes: relevant config, manager, multi_directory, orchestration/runtime, agents and team_view
code, corresponding schemas, focused tests, docs/spec and this task directory. No production config,
journal or MySQL mutation is authorized; implementation and fake/fixture verification only.
Use existing browser fixture routes and focused Node tests only. No full tests or live provider calls.
Follow .trellis/spec/core/web-console.md and design-retry-budget.md. The repository lacks Trellis
task scripts; maintain this record manually as in the previous task.

Rollback: before any new-policy Task exists, stop operations, revert this change and convert the
canonical Designer config back to the previous field. Once new-policy Task facts exist, retain a
compatible reader and fix forward; do not delete fields or rewrite immutable history to downgrade.
No production database or journal mutation is part of this implementation.

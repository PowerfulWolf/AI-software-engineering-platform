# Planner test matrix repair

Fix joint Planner combining `manual_ui` and `accessibility` into the unsupported
`manual_ui_accessibility` label and the misleading model-service failure guidance.

## Acceptance / scope

- New Planner input contains exact per-unit, per-criterion test levels. Output schema and
  prompt require separate exact design levels, not concatenated labels.
- Deterministic test-matrix validation reports typed missing coverage without relaxing it.
- Only this typed coverage rejection automatically requests correction, within the existing
  configured Planner work limit; each response and rejection remain durable across restart.
- Provider outages retain separate transient accounting. Other errors/permissions/approval
  failures are not swallowed. SIMPLE generation must not loop without spending attempts.
- UI distinguishes plan validation, output format and provider errors, including the legacy
  COMMAND_REJECTED operation already saved on this Requirement.
- Existing checkpoint/approval/feedback hashes remain readable; no production data rewrite,
  live model invocation or automatic user Requirement continuation during verification.

Allowed: relevant domain, multi_directory, web_console and team_view code/tests, generated
schemas, docs/contracts.md, .trellis/spec/core and this task directory. Single agent, current
checkout, incremental tests only, commit requested. No database migration.

Rollback: revert code/schema together before publishing extended feedback. After publication,
retain compatible readers or roll forward; never erase immutable feedback for downgrade.

# Current candidate verification plan selection

## Goal and observed failure

On 2026-11-02, K1 plan `21b0f7c2…` was newer than completed plan `86f3da85…` but its Python
dependency fingerprint had drifted. The public exact approval Operation returned an approval card
for `86f3da85…` and created no authorization for `21b0f7c2…`. This was a stale plan selection bug.

## Scope and acceptance

- Select the newest sealed plan for the current candidate before current-facts validation.
- If that plan is stale, return no reusable plan so the public resume path proposes a fresh one.
- Preserve historical plan integrity checks, old candidate filtering, admissions and completions.
- Keep K1 Task, ProductSpec, Design, Plan Artifact and existing verdict facts unchanged.

Allowed paths: `src/ai_software_engineer/recovery/verification_entry.py`,
`tests/recovery/test_latest_verification_plan.py`, this task record and
`.trellis/spec/core/verification-environment.md`. No Schema or database change.

## Verification and rollback

Run the focused recovery tests, Ruff check and format, Mypy on the changed Python file, and
`git diff --check`. Before release, confirm the active K1 Operation has completed; then use the
controlled service restart. Roll back the code commit only after checking current plan facts,
because historical plans and approvals remain append-only and older code may display an old plan.

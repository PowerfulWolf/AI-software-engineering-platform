# T038 — Actionable joint Planner coverage rejection

## Goal and authorization

User authorizes Astra to repair platform workflow bugs in this source repository; the platform
alone implements the default-platform-root feature in the separate requirement repository.
Real execution rejected an incomplete integration plan, but did not persist missing coverage.

## Scope

Derive explicit required acceptance/unit/interface IDs from approved facts for Planner context.
For the existing incomplete acceptance/write-unit coverage guard, persist safe missing IDs and
rejected-plan digest in a new immutable checkpoint next_action before returning the error.
Resume reuses approved Product/Design, receives the rejection, and consumes the existing budget.
No auto-approval, auto-fill of plans, verdict changes, schema expansion or increased retries.

Allowed paths: multi_directory/models.py and service.py, focused tests and relevant specs/task notes.
No default-platform-root implementation. No provider output/secret dump or historical rewrites.

## Acceptance and verification

- Regression at real service/journal seam: missing acceptance and write unit both reject.
- Missing IDs/hash survive restart and reach the next Planner input.
- Explicit required IDs exactly match validator's computation; valid retry reaches delivery only.
- Repeated failures preserve three-call budget; no Coder/QA/Review verdict is fabricated.
- Targeted/full pytest with MySQL, Ruff, Mypy, build and diff checks.

Rollback: retain old fixed executor/immutable journal; use source parent 3754cc4.
New context only applies to future calls, never reinterprets persisted accepted documents.

# Current provider failure plan across baseline purposes

## Goal

A current, validated `source_rebind` plan carrying `stopped_provider_failure` must
be the displayed engineering decision. The page and copied report must not ask
the user to prepare another same-source provider retry plan.

## Scope and allowed paths

- `src/ai_software_engineer/team_view/app.js`: current plan display selection and
  guidance only; preserve each purpose's existing exact submission contract.
- `tests/team_view/stopped-provider-retry.test.cjs` and the corresponding Chrome
  fixture: positive, negative, polling and detached-control regressions.
- `.trellis/spec/core/stopped-provider-ui.md` and this task directory.

## Acceptance

1. Read the newest exact successful stopped-provider or source-rebind plan;
   source-rebind requires its validated stopped-provider proof.
2. A current source plan shows its existing baseline approval, precise target,
   prerequisite confirmation and independent full native-rule review. Historical
   investigation failures remain history; no same-source preparation is offered.
3. Each approval keeps its original plan digest, PAUSE mode and confirmation
   fields. No purpose conversion, automatic submission or capability expansion.
4. Unrelated polling retains checkbox nodes, content and focus. Plan or scope
   changes reset consent and detached callbacks submit zero POSTs.
5. Non-provider source plans and invalid/foreign plans cannot suppress the
   ordinary provider preparation path.

## Validation and rollback

Run the two affected DOM suites, JavaScript syntax validation, and the isolated
Chrome stopped-provider suite using fixture-only HTTP. Review the diff separately
before commit. Roll back the UI asset/spec change and refresh the browser; no
Schema, Task, Operation, approval, database or preserved worktree changes exist.

## Stored data

No migration or direct data repair. After compatible assets load at the normal
idle maintenance boundary, refresh the existing requirement and act on its
current exact plan. Do not replay a consumed approval or alter production facts.

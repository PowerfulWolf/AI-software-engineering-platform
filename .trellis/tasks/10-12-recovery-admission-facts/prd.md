# Recovery admission facts

## Goal and scope

An authorized Task builder currently performs five full native facts inspections: two
around the first capture verification, a third solely for deterministic Task derivation,
and two around the final capture verification. The first authorization gate has already
produced the complete fresh facts needed to derive the draft. Return its final observation
as internal typed data and remove only that middle redundant inspection.

## Acceptance criteria

- Each native builder performs four complete inspect calls (eight underlying observations)
  and both original capture verifications. Derivation changes no Task wire field.
- Final authorization repeats all current Plan/receipt/path/native checks and rejects Plan
  or complete facts drift while Task derivation runs.
- Generic validate-only authorization services remain compatible and cannot invent native
  facts. No Agent, JSON API, persistent token or cross-call authority is added.
- Missing/rejected/tampered authority, changed current source/target/capture, directory
  replacement and Plan drift fail closed. No Task/authorization is overwritten on failure.
- Public exact approval and actual builder/sealing continue to enforce every retained fence;
  only the redundant native observation count changes (18 to 16 for one seal).
- No changes to MySQL fences, callback windows, dispatch, seed or model admission.

## Validation and rollback

Start with a failing actual builder count assertion. Run focused file/offline fixture tests,
Ruff, strict Mypy and diff checks; no full test suite or production runtime. The independent
root reviewer verifies the final diff before commit. Existing durable data require no migration;
loading or reverting code while idle does not approve or restart any Requirement.

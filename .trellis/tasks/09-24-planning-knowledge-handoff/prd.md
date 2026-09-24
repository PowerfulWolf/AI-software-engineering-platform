# Planning knowledge handoff repair

## Goal

Keep Planning waits at the correct visible stage and prevent repository facts or already
approved product decisions from becoming repeated human confirmation requests.

## Scope and acceptance

- Project the durable knowledge wait origin; unknown origin must not imply Product.
- Supply typed per-repository Git revision/read-root context separately from the existing
  aggregate knowledge source identity, preserving historical hashes.
- Clarify Designer/Planner responsibilities and defer missing repository facts to read-only
  inspection. A design reporting unresolved blockers cannot advance to Planning.
- Provide an exact-checkpoint, explicit recheck action for unresolved upstream Design/Plan
  gaps. Preserve Product approval and old design/gap history; do not invent a human answer,
  reset budgets, dispatch code, or mutate existing records.
- Add focused offline regression coverage and schema parity; no live model replay/full suite.

## Allowed paths

`src/ai_software_engineer/{knowledge,multi_directory,web_console,team_view}/`, relevant
`tests/`, `schemas/`, `.trellis/spec/core/`, `docs/contracts.md`, this task directory.
`pyproject.toml` and `uv.lock` raise the Pydantic floor to 2.12 for conditional serialization;
the locked version is unchanged. This preserves legacy nested artifact digests.

## Rollback

Before using the new action, revert this change's code/schema together. After a recheck
record exists, retain compatible readers or roll forward: older binaries reject the new
fields. Never delete append-only history to force a downgrade. Do not roll back a running
operation. Existing unapproved gaps are not auto-approved or silently removed during upgrade.

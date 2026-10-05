# Team snapshot wire schema synchronization

## Goal

The current typed TeamSnapshot includes Task revision/intent fields and sealed role-queue waiting
dispositions, but the published static schema omits them. Restore complete exact model/schema parity
so the declared GET contract accepts current trusted read-side facts without weakening validation.

## Allowed paths

- `schemas/team-snapshot.schema.json`
- `tests/team_view/test_snapshot_schema.py`
- The owning schema contract section in `.trellis/spec/core/live-team-view.md`
- `.trellis/tasks/10-05-team-snapshot-schema-sync/`

Do not edit runtime/domain models, remove legitimate fields, loosen additionalProperties, change
production state, operate the service or commit/push. Other workers own the reader/frontend repair.

## Acceptance and validation

1. Record the existing wire parity failure before regeneration.
2. Regenerate the complete schema from TeamSnapshot while retaining exact `$id` and `$schema`.
3. Assert complete parity, populated Task revision/intent and typed waiting-disposition roundtrip,
   legacy omitted/explicit-null optional values, unknown properties and wrong types fail closed.
4. Run only targeted schema/wire tests, Ruff and strict mypy on the new test; no full suite or MySQL.

## Stock data and rollback

This static schema has drifted behind existing typed read output; no SQL, journal or stored artifact
change is needed. Deploy the synchronized declaration with the existing model. Roll back code/schema
together while idle; preserve all Team/Project facts. Restoring the obsolete schema would reintroduce
the documented wire mismatch and is not a data repair.

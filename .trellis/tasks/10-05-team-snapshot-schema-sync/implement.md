# Implementation

- Regenerated only `schemas/team-snapshot.schema.json` from the current typed TeamSnapshot,
  preserving exact metadata and sorted object presentation. The result contains 236 added lines,
  with no deleted fields, changed models or loosened additionalProperties.
- Added `tests/team_view/test_snapshot_schema.py` with exact parity and populated typed output
  roundtrip; optional omission/null compatibility; extra-field rejection at every nested waiting
  boundary; and wrong revision/intent/disposition/hash types.
- Updated the live-team-view role-queue schema contract to document reachable definitions, full
  parity, nullable compatibility and the separate domain digest validator responsibility.

## Failure mode and stock data

Static declarations were not synchronized when already-existing typed read fields were introduced.
An actual trusted waiting snapshot was rejected as extra fields by the obsolete schema. Full-model
parity plus populated waiting fixtures prevents a sparse empty snapshot from hiding this class of
drift. No storage migration or historical rewrite is required, and no production operation occurred.

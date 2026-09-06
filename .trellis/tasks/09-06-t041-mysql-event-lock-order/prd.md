# T041 — Serialize same-Task event writers before event lookup

Full regression exposed MySQL 1213 rather than InvalidStateEvent for competing source-state
transitions. Adjacent absent event IDs reproduce this in all 10 rounds in 0.65s. Existing ordering
locks event-index gaps before contenders serialize on one Task row.

Lock Task first, then check event idempotency, then validate/apply the transition. Keep replay,
changed-event conflict, atomic event/snapshot/CAS and rollback behavior unchanged. No retry loop,
isolation-level relaxation, fake success or schema migration. Preserve event conflict behavior even
when a caller references a missing Task by checking event identity before reporting missing Task.

Allowed: MySQL repository append_event ordering, competing-connection regression, production spec.
Verify: 10-round focused race, repository suite and full MySQL suite, Ruff/Mypy/build/diff.

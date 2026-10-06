# Diagnose and bound ASE console memory growth

## Goal
Reproduce rapid process growth reported from below 1 GB to 4.4 GB, distinguish retained memory from
transient/concurrent journal reads, and repair the responsible lifecycle or read-side boundary.

## Scope and allowed paths
Console/team reader and owning journal/cache/lifecycle code only after an evidenced reproducer.
Related incremental tests, memory/diagnostic contracts, and this Trellis task. Production inspection
is read-only; no heap-content dumps, secrets, SQL writes or state/verdict/journal edits. Service
replacement only after capturing facts and verifying no active operation, via the trusted script.

## Acceptance
- Measure physical footprint (including compressed/swapped ownership), not RSS alone.
- Pin a red-capable, bounded feedback command and minimise against real read/lifecycle seams.
- Record causal evidence before fixing; no unbounded caches or weakened integrity checks.
- Repeat original memory-growth loop after the change; current/retired/history facts stay correct.
- Run incremental tests and independent review; document existing-data treatment and rollback.
- Preserve the original K1 identity, authorization and execution facts.

## Validation/rollback
No full suite. Use small fixtures and safe bounded serial/concurrent read experiments without model
calls. A production observer must not create a load flood during memory pressure. Roll back code
while idle, reload the trusted service, and retain every durable artifact/approval.

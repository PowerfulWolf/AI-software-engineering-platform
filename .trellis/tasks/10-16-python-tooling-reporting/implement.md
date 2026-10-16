# Implementation

The generic Native Coder Python tooling paragraph placed an unconditional `NOT_RUN` instruction
after its description of possible source-shadow refusal. This can be read as requiring that
status even when a source-binding inspection actually completed. K1's accepted progress is
evidence of ambiguous guidance; it does not independently prove incorrect source binding or a
business-test defect.

The tooling prompt helper now explicitly requires `NOT_RUN` for an actual launcher source-shadow
refusal, unavailable required tooling, or an unexecuted check. Completed checks must report their
actual command results. A successful source-binding check alone does not establish candidate
verification passed. The existing contract in `production-team-host.md` records the same rule.

Only prompt text and its documented contract change. The fixed bootstrap, source-shadow guard,
environment, permissions, no-install/no-repair rules, schemas, recovery and independent QA/Review
remain unchanged. Existing focused tests cover registered safe tooling and unsafe-tool guidance;
no test is added solely to mirror the revised prose.

## Existing data disposition

No persisted record is rewritten. Historical K1 `NOT_RUN`/`FAIL` entries, evidence, approvals and
state remain immutable. Any new verification must run through the original delivery path and
report its own actual result. The currently executing K1 request is already sealed and is not
changed by editing this prompt helper.

Deploy with the pending progress-continuity change only at the safe idle boundary. Roll back by
reverting this prose change after a controlled stop; retain all delivery history. This is a
semantic clarification, not proof that a real model will always interpret it correctly or that
any historical failure is resolved.

# Design

Use an internal typed receipt-reference contract produced by trusted verification providers.
Carry it alongside the prompt without serializing it to model-facing messages or durable
artifacts. The native adapter retains the contract for exactly its prepared request and checks
the decoded role output before returning SUCCEEDED or publishing a result. Report decoding,
producer/source/lineage, candidate/worktree and execution guards remain independent gates.

The contract is reading provenance, not execution authority: it cannot authorize a new test,
model invocation, state transition or approval. Derive required receipt URI/SHA and criterion
coverage from already verified typed Plan/receipt; never parse model prompt JSON to discover
trust. No general-purpose validator callback or mutable trusted state is exposed to agents.

Check only current controlled output claims. Genuine upstream background evidence remains legal;
source-only inspection with no controlled test has no fabricated receipt. Do not automatically
repair model output or fill its evidence array. Reject mismatch through safe INVALID_OUTPUT or
the established typed verification wait where current facts changed.

Controlled runners have no expected-nonzero command mode: a true negative test asserts the
expected denial and exits zero. Actual nonzero required checks cannot support QA PASS or
Review APPROVE. Preserve honest QA FAIL/Review REJECT and mixed per-test results; this gate
rejects contradictory positive output and does not synthesize a negative verdict.

The broad native Coder command-capture limitation is recorded, not hidden by adding a model-
writable log. Real independent QA/Reviewer must produce new evidence for the final candidate.
The exact helper signatures and tested field map will be recorded before implementation.

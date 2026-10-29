# Static QA source gap for a frozen pytest function

## Scope and trigger

An accepted candidate may contain a planned `test_*.py` file while lacking the
exact function named by a frozen `python -m pytest -q path::test_function`
selection. The current independent QA role may be waiting because the complete
controlled verifier is unavailable. The platform may use a narrow source-level
proof to let independently claimed QA report that deficiency and return work to
Coder. This is not a substitute for dynamic pytest collection or any original
browser, MySQL or A→B acceptance run.

## Signatures and fields

```python
observe_accepted_candidate_test_entry_absence(
    repository_root, task, repository, source_revision, accepted, artifacts,
    include_named_nodes=True,
) -> CandidateTestEntryAbsenceObservation
static_qa_missing_entry_output_contract(
    request, *, observation, sealed_no_start_proof_sha256,
    authority_sha256, claim_sha256, all_criterion_ids
) -> TrustedStaticQaMissingEntryOutputContract
validate_static_qa_missing_entry_output(request, artifact, contract) -> None
```

`MissingPlannedTestEntry.node_id` is optional. If present, it is the complete
frozen `path::test_function` selector; if absent, the historical record means
the planned file was missing. `StaticQaMissingEntry.node_ids` groups all named
gaps by path for the independent QA output and knowledge scope. Both optional
fields are omitted from old wires. The observation digest removes only absent
`node_id` fields, preserving the old v1 missing-file SHA and all existing
null fields in nested original row wires.

## Contracts

The observer first validates the current Task in QA, accepted Plan event,
implementation parent chain, candidate commit, frozen QA row, exact planned
path and Git tree. It only reads a regular candidate Git blob through bounded
owned Git commands, max 64,000 bytes, strict UTF-8 and Python AST. It accepts
the exact five-token pytest argv above and a simple module containing only an
optional docstring and explicit `from ... import name [as alias]` statements.
A direct definition, named reexport or any syntax that could dynamically
create a binding makes the named absence unavailable. The observer never
imports or runs candidate code.
An oversized, syntactically invalid or undecodable existing file proves no node
gap for that row; it does not discard a separately proved missing file. A Git
tree/object identity error, unreadable object or blob size/body mismatch rejects
the entire observation. When rereading
an already sealed observation whose entries all lack `node_id`, both wait
resolution and later QA claim validation use the original files-only mode.
This rechecks its original digest against the unchanged candidate and Plan
without silently expanding a historic decision to newly detectable nodes.

The public `InspectDeliveryWait` still proves the original verifier
`NOT_STARTED`, no role invocation start/outcome, current Requirement/Task and
two historical claims. `ResolveDeliveryWait(STATIC_QA_MISSING_ENTRY)` consumes
the exact proof once under the queue fence. A fresh QA claim gets only the
static proof scope. Its trusted prompt distinguishes a missing file from an
existing file without the frozen direct source binding, includes each complete
`path::test_function` selector, and states that the planned command and dynamic
collection were `NOT_RUN`. The QA output gate rereads current authority, claim,
candidate and proof; it accepts only a QA-authored `FAIL`, no `tests_run`, one
file proof evidence, `MISSING_PLANNED_TEST_ENTRY` findings and `NOT_TESTED`
for unrelated criteria. The internal contract binds the complete acceptance
criterion ID set from the same current Task snapshot checked by the claim
proof. Its prompt lists all IDs, the proof-affected FAIL IDs and the remaining
NOT_TESTED IDs. The output gate requires `criteria_results` to cover the
complete Task set exactly once before a QA report is accepted by the adapter;
the Orchestrator repeats that check before routing. This prevents a report
that covers only the source-gap criteria from being accepted by the adapter
and rejected later by the Orchestrator. The ordinary FAIL route sends findings
to Coder.

The investigation `next_action` is guidance derived from the sealed source-gap
observation, never an additional permission. A file-only observation retains
the historical wording byte for byte. A named-node observation says the file
exists and lacks only a direct source binding; a mixed observation describes
both kinds of gaps. Both state that the original command and dynamic collection
did not run. The text must not claim the file is missing for a node-only proof
or claim that dynamic pytest collection cannot find the node.

## Validation and error matrix

| Input | Result |
| --- | --- |
| Simple import-only file lacking frozen named binding | Seal exact node source-gap observation |
| Direct function or named alias reexport | No gap observation |
| Star import, assignment, decorators, dynamic top-level or malformed source | No static decision; preserve wait |
| Missing file | Existing missing-file observation and unchanged digest |
| Node-only or mixed source gap | Investigation guidance identifies the actual gap; permitted resolution remains the same exact one-use kind |
| Sealed missing-file proof plus a different row with a new node gap | Recheck the old proof in files-only mode; retain its exact digest |
| Missing file plus unrelated existing source above 64,000 bytes | Preserve the provable missing-file observation; make no claim about that node |
| Missing file plus drifted or unreadable Git blob for another row | Reject the entire observation; publish no partial proof |
| Changed candidate, Plan, original no-start or current claim | Reject decision/output; no role verdict |
| QA claims command ran, PASS, wrong evidence or unrelated criterion PASS | Reject output |
| QA omits any current Task criterion or adds a foreign criterion | Reject before accepting its artifact or queue result |

## Good, base and bad cases

- Good: a public one-use engineering decision leads to independent QA source
  FAIL, then an ASE Coder repair attempt and later complete QA/Review.
- Base: the file directly declares the exact test function; continue ordinary
  complete verifier preparation without a static source decision.
- Bad: run manual `pytest --collect-only`, copy its text into a QA report and
  mark the original A→B behavior as checked.

## Required tests and review points

`tests/manager/test_candidate_test_entry_absence.py` checks Git blob, simple
AST cases, uncertainty, old digest, mixed historic rows, oversized source and
Git object drift.
The wait/claim regressions must exercise the files-only recheck on both sealed
decision paths. `tests/agents/test_static_qa_missing_entry_output.py`
checks grouped node IDs and the proof-only FAIL contract.
`tests/knowledge/test_static_qa_scope.py` checks the named-node disclaimer and
old scope wire. `tests/agents/test_static_qa_adapter_transport.py` checks the
actual PromptBuilder text and internal contract. `tests/manager/test_public_static_qa_node_gap.py` uses isolated
MySQL and public Host APIs to check Inspect → Resolve → new QA claim →
proof-bound FAIL → Coder routing. It must also show the original candidate and
history remain intact, and the prompt must include the complete Task criterion
set. Ruff, strict Mypy, schema generation and the older
missing-file public integration are release gates.

## Wrong and correct

Wrong: treat the existing file path or a green unrelated imported test as proof
that the frozen `path::test_function` exists, or let the platform author QA FAIL.
Correct: bind a narrow source observation to the exact candidate and frozen
selector, then let separately claimed QA inspect it and author the verdict.

## Stored data and rollback

No migration or production DB/sidecar rewrite is required. Existing K1 Task,
candidate, old start-only UNKNOWN and `WAIT/NOT_STARTED` records remain intact.
Previously sealed investigation text and its SHA remain immutable. A node-gap
investigation sealed before corrected guidance but not yet consumed requires a
fresh public inspection after the new version; an already consumed decision is
read by its sealed proof and is not rewritten.
An already accepted QA artifact that omits Task criteria cannot be reinterpreted
as a valid verdict by this prospective output gate. Preserve its exact bytes,
original claim, failed Orchestrator result and wait; recovery requires a
separate exact engineering decision and fresh independent QA claim.
Before a new public static decision, rollback the platform change at an idle
boundary. After a decision or role artifact is sealed, preserve compatible
readers and fix forward; never erase the new audit trail or replay a consumed
decision.

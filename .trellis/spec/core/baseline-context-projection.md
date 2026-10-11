# Mode-aware execution baseline Context

## Scope and signatures

Implementation entry points are `context/execution_baseline.py`,
`orchestration/execution_baseline.py`, `manager/execution_baseline.py`,
`agents/candidate_binding.py`, `manager/native_verification_facts.py` and
`recovery/baseline_source.py`, under `src/ai_software_engineer/`.

`BaselineRunContextBuilder.build(...) -> ContextBundle` continues to resolve the complete
store-verified baseline and retained UTF-8 patch before compiling a required section.
`ExecutionBaselineContext` is the unchanged legacy body containing `binding`, `instructions`
and `complete_patch`. `PreservedWorktreeBaselineContext(schema_version="v2")` is a bounded
reading projection for `input_mode=preserve_draft`: complete typed binding, accurate instructions,
and the exact retained patch URI/SHA/byte reference. It does not contain the patch again.

`parse_execution_baseline_context(content)` reads either exact version. New `coder_reapply`
contexts always retain the entire original patch body. Existing v1 contexts remain readable and
their content/digest are never changed.

`execution_baseline_from_context(context, request, task, *, verifier=None)` requires an explicit
`ExecutionBaselineContextVerifier` for v2. Its `require_current(binding, task)` reopens complete
store history, exact operation/authority/native epoch and retained patch body before accepting
the projection. Missing evidence, a different current binding, or an absent verifier refuses;
v2 never falls back to v1. The projection cannot establish authority, a process stop, or a verdict.

## Data flow and invariants

Full immutable plans/captures/inventories/patches -> trusted resolver validation -> mode-aware
required Context -> independent provider role -> exact candidate Artifact -> independent QA/Review.
Preserve mode already materialized and admission-checks the retained worktree. Repeating its
complete patch in every prompt wastes input without granting new execution rights. Reapply mode
starts clean and still requires the complete old patch as actual role input.

The full `ExecutionBaselineBinding` retains Task intent, Team/Project/Repository scope,
approved/execution source, branch/path, prior chain, source artifacts, native-rule epoch,
plan/facts/authority/inventory and original stop-proof references. All existing native-rule,
candidate SHA/lineage, latest-binding, WorkItem/Lease and write-policy gates remain unchanged.
QA/Review still receive the complete current-base-to-candidate diff through `BoundCandidateSource`.

## Validation matrix and tests

| Case | Required behavior |
| --- | --- |
| Large preserve draft; all three delivery roles | Required v2 is small; exact full patch verified in store; original worktree unchanged |
| Coder reapply | Entire UTF-8 old patch remains present and length/SHA checked; no truncation |
| Historical v1 Context | Original serialized body and digest read unchanged |
| v2 without verifier, missing/corrupt patch or authority | Refuse before candidate/source acceptance |
| Foreign Task/scope, altered reference, stale binding or native epoch | Refuse even with recomputed section digest |
| Knowledge consultation finalized Context | Verify exact existing section, preserve final Context identity |
| Candidate QA/Review | Complete actual candidate diff and independent verdict gates unchanged |

Incremental tests cover the real BaselineRunContextBuilder pipeline with generated large patches,
v1 compatibility, reapply, preserved source, missing evidence and candidate/native/terminal readers.
No production patch or prompt is copied into the repository.

Good: a new preserve Context is constructed only after reading complete evidence; every v2
consumer reopens the store, checks the exact Context/request identity and requires the current
binding. Base: a historical v1 Context keeps its complete body, content SHA and finalized Context
ID; a new reapply Context also contains the full old patch. Bad: trust a reference without a
verifier, truncate a required patch, rewrite a historical Context or interpret a projection as
authority to run, a real process stop, or a passing verdict.

Run `PYTHONPATH=src .venv/bin/python -m pytest tests/context/test_baseline_projection.py
tests/manager/test_execution_baseline_context.py tests/recovery/test_terminal_baseline_context.py -q`
for the contract/consumer increment. Coordinate the shared MySQL window before the public
`tests/manager/test_production_execution_baseline.py` delivery increment. The tests assert that
large preserve input fits, complete patch SHA/bytes stay unchanged, missing evidence refuses,
legacy bodies are unchanged, and QA/Review consume one actual candidate.

## Existing data and rollback

No SQL, Task, approval, source binding or historical Context migration applies. Existing full
contexts and original failed invocation records remain immutable. A future separately authorized
execution receives a new Context digest built from the same verified source binding; this change
does not grant a replacement call, refund work, or waive a stopped/unknown outcome. Root owns the
public continuation path for K1. Deploy only at a controlled idle service boundary.

Rollback before any v2 Context exists can revert the feature. Once v2 exists, retain its read
support and complete-evidence verifier while disabling new v2 generation; do not remove durable
contexts or treat a digest as the omitted evidence body.

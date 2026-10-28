# Implementation plan and release gate

## Ownership and allowed paths

This work may change only the ASE platform modules needed for a versioned engineering decision,
recovery Context selection, candidate admission and public continuation, their matching tests,
static Schemas and generators, `.trellis/spec/core/` executable contracts, and this task folder.
The target K1 repository worktree, frozen ProductSpec/TechnicalDesign/ExecutionPlan, sealed
RecoveryPlan and production MySQL records are read-only until a separately verified public
operation consumes an exact decision.

Proposed initial path inventory (expand only after reviewing a concrete diff):

- `src/ai_software_engineer/domain/delivery_resolution.py`
- `src/ai_software_engineer/manager/{delivery_wait,production_backend,production_delivery}.py`
- `src/ai_software_engineer/orchestration/{context,retry}.py`
- `src/ai_software_engineer/recovery/{context,seed,inherited_input}.py`
- `src/ai_software_engineer/orchestration/execution_baseline.py`
- `src/ai_software_engineer/agents/{codex_cli,openai_compatible}.py`
- `src/ai_software_engineer/web_console/{models,manager,transport}.py`
- Matching `tests/`, `schemas/`, schema generation scripts, `.trellis/spec/core/`, and docs.

This inventory is an implementation forecast, not permission to alter protected paths outside
the platform maintenance repository or to rewrite K1 facts. A generated Schema touching other
paths requires exact review before publication.

## Contract-first sequence

1. Add failing pure tests for source inventory, accepted-progress selection and complete coverage.
2. Add failing isolated public tests for the current pre-Context capacity wait, exact engineering
   approval, no-model-start preservation, serial Coder progress and final candidate/QA/Review.
3. Implement immutable decision and Schema, Context selection and legacy strict compatibility.
4. Implement exact accepted-progress/claim proof at each advance and pre-commit candidate gate.
5. Wire the public resolution/queue re-claim, update Console projection, and verify crash replay.
6. Run Ruff, Mypy, relevant unit/contract tests and guarded isolated MySQL fixture; inspect the
   final diff against the allowed paths and independent role separation.

## Release and rollback

Do not release an intermediate slice. Publish only after the public fixture proves the complete
same-Requirement path and an independent reviewer checks code/spec alignment. Deploy on a clean
platform `main`, push, then use the documented controlled restart. The original K1 is resumed
only through the public interface with a new idempotency key. A failed operation remains history.

If a decision is not consumed, an idle rollback can disable activation. If consumed, retain
compatible decision/Context readers and fix forward; do not remove it from the store or reset
the old wait, Task, Run, or approval.

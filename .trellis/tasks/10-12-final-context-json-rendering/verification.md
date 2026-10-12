# Final Context rendering within the original input budget

## Goal and scope

A complete Coder reapply Context can fit its section budget while the final native
prompt plus strict output schema exceeds that budget because JSON section bodies
are escaped again and READ chunks repeat their lexical term indices. Keep complete
approved inputs and required patch/read text, with the original 256,000 limit.

Allowed changes: `agents/context_rendering.py`, `agents/openai_compatible.py`,
`tests/agents/test_context_prompt_rendering.py`, this task and a dedicated core spec.
The change is prompt-only; no SQL, Task, approvals, Context, evidence or native rules
are written or migrated.

## Contracts

- JSON object/array sections become structured prompt values with `content_format=json`.
- Duplicate keys, NaN/Infinity, overflowing or precision-losing float literals,
invalid JSON and primitive text retain the original complete string.
- `knowledge-read-v1` retains every original READ field and complete chunk text,
except `chunk.terms`, after typed evidence integrity, READ operation, chunk SHA and
`terms(chunk.content)` prove it is exactly the derived lexical search index.
- Both format and omitted field are explicit. SHA fields identify original sealed
Context bytes. Stored Context and knowledge gate evidence remain unchanged.
- Final `BoundModelInputBudget` still checks actual prepared provider material,
including the complete strict output schema. No larger capacity is inferred.

## Validation

Initial new JSON-rendering tests: 2 failed / 7 passed before implementation.
The new native regression runs the original text renderer to reproduce overflow,
then checks actual `CodexCliAgentAdapter.prepare_input`, complete patch/read text,
full schema reuse, zero provider calls and cleanup at the original 256,000 limit.

```text
PYTHONPATH=src python -m pytest -q tests/agents/test_context_prompt_rendering.py \
  tests/agents/test_openai_compatible.py tests/agents/test_model_input_preflight.py
54 passed in 2.51s

PYTHONPATH=src python -m pytest -q tests/knowledge/test_prompt_projection.py \
  tests/knowledge/test_delivery_context.py
28 passed in 1.44s
```

Strict Mypy for both changed production files and the new tests, Ruff and diff
whitespace checks passed. No full test suite or production mutation was run.

Read-only actual sealed K1 Context comparison with an equivalent fixture request,
complete native prompt compile and complete schema: old rendering 281,125 tokens;
new rendering 254,540 tokens at unchanged 256,000. Actual work-slice, continuation
and random support-tool paths may add overhead; this measurement does not waive
final preparation or prove the historical execution runnable. The public recovery
and exact real-input receipt are owned by the coordinating task.

## Existing data, risks and rollback

Old failed invocation, terminal Task, attempts, leases, approvals and Contexts are
immutable. This patch alone does not reopen K1; use the separately verified public
terminal compatibility path. If complete final input still exceeds capacity, the
separate typed engineering-capacity wait must preserve the checkpoint and expose
the exact gap; never trim required input.

Rollback may revert the prompt-only renderer at an idle controlled service boundary.
All persisted Context/evidence remain readable because their schemas and bytes did
not change. A rollback may reintroduce final input overflow but cannot drop evidence
or bypass final preflight.

Additional serializer compatibility check after adding numeric precision-loss case:
`tests/agents/test_context_prompt_rendering.py tests/agents/test_responses.py`:
38 passed in 2.22s. Ruff format check also passed for all three Python files.

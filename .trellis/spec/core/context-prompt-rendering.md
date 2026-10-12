# Complete Context reading representations

## Scope and signatures

`agents/context_rendering.py` provides
`render_context_section(section: ContextSection) -> PromptSectionRendering | None`.
`ContextPromptBuilder` uses it only to render a model's reading input; it does not
replace a Context, artifact, evidence or knowledge snapshot in any store.

## Input and output contracts

An unambiguous object/array JSON section uses `content_format=json`, complete
structured values and `source_content_sha256`. The ordinary `sha256` continues
to identify the original sealed Context section bytes. Section order, original
name and URI remain unchanged. System instructions explain the representation
and state that it creates no execution or verdict authority.

Duplicate object keys at any depth, non-finite numeric constants, floating point
overflow/precision loss, invalid JSON and primitive prose remain the original
complete text. No permissive parse may silently discard information.
Escaped lone surrogate keys/values, Decimal exponent errors and nesting beyond
the typed JsonValue recursion limit also retain the complete original UTF-8
text. Optional reading optimization must never make an otherwise readable
sealed Context fail. Verify both typed values and UTF-8 serialization before
using structured content; ValidationError is not a verdict or corrupt record.

`knowledge.reads` additionally permits `content_format=knowledge-read-v1` and
`omitted_derived_fields=["chunk.terms"]`. Before applying it, the renderer parses
all items as `KnowledgeEvidence`, validates each immutable evidence digest, requires
`read_knowledge`/`READ` with a real chunk, checks the full chunk text SHA and proves
`chunk.terms == knowledge.retrieval.terms(chunk.content)`. This field is the sorted
lexical search index derived deterministically from the same complete text; it is
not an independent rule or reading passage. All other original fields, including
complete chunk content/citation/title/path/ordinal, binding, evidence ID, request
SHA, operation, empty arrays and explicit nulls, remain their exact original values.
If any item is invalid or its terms are not the exact derivative, keep original
text and let ordinary trusted gates handle the invalid facts.

## Data flow and invariant

Original complete sealed Context -> strict prompt reading projection -> actual
native/Responses serialization -> unchanged `BoundModelInputBudget` preflight ->
real invocation. The knowledge delivery gate still recomputes the original full
READ section from original typed evidence. A projected prompt does not establish
new lineage, approvals or knowledge facts.

Avoiding repeated JSON escaping and verified lexical indices reduces input overhead.
It does not enlarge declared model capacity, truncate a patch, remove an approved
rule or select fewer READ passages. Final preparation still includes strict output
Schema, wrapper, continuation and source package; section-token totals alone never
prove that a call fits.

## Validation matrix

| Input | Expected result |
| --- | --- |
| Complete object/array JSON with Unicode, escaped patch, booleans and null | Same structured values and explicit JSON format; sealed Context bytes unchanged |
| Duplicate key/nested duplicate/non-finite/precision loss | Preserve original complete text |
| Escaped lone surrogate, extreme Decimal exponent or excessive typed nesting | Preserve complete original text through the actual ContextPromptBuilder |
| Valid typed READ with exact derived terms | Preserve every field and chunk body except the declared redundant lexical index |
| Changed terms/body, invalid evidence digest or unknown field | Preserve original complete text; do not strip potentially meaningful input |
| Original complete native prompt+schema exceeds 256,000; rendered one fits | Zero provider during prepare; same required patch/READ text, actual schema included |
| Still oversized after rendering | Existing final-budget guard refuses; no invocation start or implicit capacity increase |

Incremental checks are `tests/agents/test_context_prompt_rendering.py`,
`test_openai_compatible.py`, `test_model_input_preflight.py`, and
`tests/knowledge/test_prompt_projection.py`, `test_delivery_context.py`.

## Existing facts and rollback

No Context, knowledge, Schema or SQL migration applies. Old persisted hashes remain
valid. Rollback can disable the prompt-only projection while keeping all durable
facts unchanged; old overflow may return and must remain a capacity refusal.

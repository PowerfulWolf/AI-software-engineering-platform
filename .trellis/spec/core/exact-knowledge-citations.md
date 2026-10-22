# Exact knowledge assessment transport citations

## Scope and failure mode
Knowledge assessment can copy a 64-digit chunk ID incorrectly while satisfying the static shape schema. K1's second semantic rejection changed two characters in one READ chunk ID, twice. Rejecting the output remains correct; avoid inviting arbitrary citation construction in future output contracts.

## Signatures and ownership

```python
# knowledge/assessment_validation.py
assessment_output_schema(citations: tuple[KnowledgeCitation, ...]) -> dict[str, object]
# knowledge/assessment_rejection.py; called only after original evidence is verified
_require_requests(records, binding, input_sha256, intent_outcome,
                  assessment_outcome, evidence, manifest: KnowledgeRunManifest) -> None
```

`KnowledgeConsultationService.consult` passes `skills.manifest().citations` to the helper immediately before its assessment call. The new transport definition is `$defs.KnowledgeCitation.anyOf`: every alternative retains the typed object's properties/required/additionalProperties=false and binds all six properties with `const`. Complete duplicates reuse their first occurrence in the ordered READ sequence. Empty READ sets `properties.claims.maxItems=0`; KnowledgeClaim itself still requires a nonempty citation list.

`_require_requests` recomputes `structured_request_digest` separately for the original static `KnowledgeAssessment.model_json_schema()` and the exact helper result, with identical original input, instructions and timeout. A digest outside that two-element set raises `ASSESSMENT_REJECTION_REQUEST_CHANGED`; all admission/receipt/semantic gates still run.
The knowledge application derives a transport-only assessment schema from the exact Run manifest before assessment. KnowledgeAssessment and KnowledgeCitation persisted domain schemas remain unchanged. The pure helper accepts complete typed READ citations, never search-only hits, guessed paths or caller-supplied permissions.

## Contracts
Each permitted citation must be a complete exact object: document_id, scope, document_sha256, chunk_id, chunk_sha256 and source_uri. A union of fully fixed objects preserves tuple identity. Independent per-field enums are prohibited because they permit cross-object combinations. Deduplicate deterministically. No READ permits no citation; it must not prevent a zero-claim GAP response. The final semantic membership and redaction gates always remain active if a provider ignores output constraints.

Historical rejected-assessment rederivation accepts exactly two reproducible request formats: the original static output schema, or the new exact READ schema derived from the original full ordered evidence/manifest. Stored request_sha256 must equal one complete reconstruction. Instructions, input, timeout, claim identity, admissions, completions, READ proof and result digests remain fully checked. Do not use exception/error text to select trust, mutate instructions globally, modify an old citation or change historical bytes to fit the new format.

## Validation and error matrix
| Input | Result |
| --- | --- |
| Complete object present in this Run READ set | Transport-representable; ordinary semantic checks still apply |
| Typo or cross-object field combination | Schema rejects; final membership also rejects |
| Search-only, foreign Run or no-READ citation | Not permitted |
| Empty READ with zero claims | Representable |
| Original static request or new exact request | Exact independent reconstruction required |
| Another schema/input/timeout/claim hash | Refuse; preserve history |

## Good / Base / Bad
Good: choose a complete citation supplied by a real READ. Base: reopen the original K1 static-request rejection unchanged after deployment. Bad: add six independent enums, repair a prior hash, skip membership, or treat constrained schema as an acceptance verdict.

## Required checks
Real schema red/green at the consultation transport; actual K1-style two-character typo; complete-tuple mix; empty/duplicate READ; provider ignoring constraints; old and new rejected request rederivation and unrelated request tamper rejection. Run focused knowledge/native/HTTP recovery tests plus scoped Ruff/strict Mypy. Fixtures do not establish K1 candidate or independent QA/Review.

## Existing data and rollback
No SQL migration, new product approval, baseline replacement or budget reset. The exact original wait is recovered only after full investigation and trusted ENGINEERING resolution. Preserve complete current draft, original erroneous output and every claim/event. Upgrade at idle through controlled stop; never interrupt an active role to load this change. Rollback may disable new schema production but must retain compatibility for any new request already sealed. A consumed recovery decision cannot be erased by reverting code.

## Wrong versus correct

Wrong: constrain each of the six fields independently to every READ value; this permits a fabricated tuple assembled from different sources. Also wrong: replace the global domain schema/instructions and thereby invalidate old request hashes.

Correct: `assessment_output_schema(manifest.citations)` constructs complete fixed alternatives only for this Run. The independent historical reader reconstructs either exact known request format; `assessment_rejection_reason(assessment, manifest)` always enforces full typed membership.

Focused verification uses the project Python with `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/knowledge/test_assessment_schema.py tests/knowledge/test_assessment_rejection.py tests/knowledge/test_consultation.py`. The schema tests assert both raw and `strict_output_schema` forms, full-tuple identity and empty/duplicate READ behavior; rejection tests assert legacy/new request compatibility and unchanged provider-noncompliance rejection.

# Design

## Contracts
A pure helper derives the assessment transport JSON Schema from the immutable Run manifest's exact READ citations. Keep KnowledgeAssessment's static Pydantic schema and persisted wire unchanged. Use complete-object anyOf branches with fixed field values, retaining required properties/additionalProperties=false. Do not enum each field independently. Deduplicate complete objects deterministically and preserve bounded evidence order. Empty READ sets prohibit nonempty citation arrays while allowing no claims.

Online consultation obtains its manifest before assessment and supplies the exact schema. The final assessment_rejection_reason still compares full typed citations with the same manifest.

Historical request reconstruction builds two deterministic candidates from original full evidence: original static schema and new exact schema. Accept only an exact stored request digest matching one candidate; all original instructions, input, timeout, claim and route proofs still match. Never change old instructions, cite IDs, RETURNED payloads or wait classification. This compatibility is a finite format choice, not a retry/error fallback.

## Validation matrix
Good: any complete READ citation can be used. Base: an old static-schema request and its immutable rejection reopen unchanged. Bad: two-character digest typo, mixed fields from two valid objects, fabricated/foreign/empty-set citation, request hash outside the two exact forms. Provider noncompliance still reaches INVALID_OUTPUT.

## Recovery
After tests and independent review, integrate runtime fix, controlled stop/start at no active claim, inspect exact original wait, handle complete proof and operator-resolve exact current draft. Public Resolve alone consumes one ordinary allowance, creates successor/new claim and preserves old results. Verify actual main start, not merely Operation success or queue claim. Continue genuine repository-inspection gaps under existing authority without supplying invented facts or future QA results.

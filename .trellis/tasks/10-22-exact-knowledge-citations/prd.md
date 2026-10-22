# Bind knowledge assessment output to exact READ citations

## Goal
Prevent repeated citation transcription errors while retaining strict exact READ admission and every historical request digest.

## Observed defect
K1 work_2d891a9e1a2cec543381a40bb710508f3988973b8f9e0be9f19a4c7aa3dd9947 returned two citations with a two-character chunk_id change. Observation4434f403336ef081dda52d25564a536f18c824f4dcdc0de56a808e535409d438 independently rederived from original records. The existing INVALID_OUTPUT gate is correct. Current transport schema permits any digest-shaped citation, despite an exact finite READ set.

## Scope and authorization
Delegated platform engineering maintenance under the user's instruction to repair, approve and continue original K1. Allowed production paths: src/ai_software_engineer/knowledge/assessment_validation.py, agents.py, assessment_rejection.py and one focused knowledge schema helper if needed; focused tests/knowledge/**; this task directory and .trellis/spec/core/exact-knowledge-citations.md plus index.md. Target runtime source b2c634409dd145639f2147600ee792e8175e04f9. Original K1 source5547815464a04991f50a2e0532d6f2f13d8daa69 and its frozen ProductSpec/Plan are unchanged. No persistent contract/SQL migration, global instruction change or rewriting prior outputs.

## Acceptance
- [ ] Future assessment schema permits only complete exact citations actually READ in that Run, and rejects digest typos and cross-object field combinations.
- [ ] Empty READ cannot authorize a citation; zero-claim responses remain representable.
- [ ] Final semantic exact membership gate stays enforced even if provider ignores schema.
- [ ] Old static requests and new exact requests independently rederive; other request digests are refused.
- [ ] No schema regeneration or old wire/hash changes.
- [ ] Real red/green, focused knowledge tests, Ruff, strict Mypy and independent read-only review pass.
- [ ] Deploy only at verified idle controlled-stop boundary; recover original K1 through exact public engineering resolution with complete current draft and unchanged budget.

## Rollback
Code reference b2c6344. After a new exact request exists, keep the compatible request reader even when disabling prospective schema production. Retain all decisions, raw sealed results and histories. Use controlled stop before runtime replacement; no SQL reset.

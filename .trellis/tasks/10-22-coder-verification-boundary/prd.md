# Coder implementation and independent verification boundary

## Goal and evidence

Correct generic platform prompt ambiguity without changing approved Task/Plan scope,
source, permissions, budget, Context bytes or historical reports. K1 attempt7 retained
26 lawful dirty paths but again deferred steps03–08 while requesting an isolated SQL
verifier. Its immutable Plan assigns all61 structured verification requirements to QA.
This does not prove SQL absence was the sole cause of slow progress, or that all
remaining implementation can safely finish without a database.

The shared final-slice prompt currently says all "required verification" must finish
before an implementation report. Native tooling guidance sends missing-tool cases to
coder-progress without distinguishing Coder checks from independent QA prerequisites.
The machine candidate gate already accepts honestly recorded NOT_RUN checks; independent
QA/Review remain mandatory. Fix the prose to express that existing boundary precisely.

## Allowed paths and implementation

- src/ai_software_engineer/agents/openai_compatible.py
- src/ai_software_engineer/agents/codex_cli.py
- tests/agents/test_coder_slice_output_guidance.py
- .trellis/spec/core/coder-slice-output-guidance.md
- .trellis/tasks/10-22-coder-verification-boundary/**

Add shared Coder-only system guidance for both prompt builders and therefore native
execution. Missing independent QA prerequisites alone must not prevent other allowed
implementation. Preserve genuine implementation dependencies and explicit Coder checks;
never infer completeness, claim NOT_RUN as PASS, or bypass frozen slices and original
candidate/QA/Review gates. Do not add arbitrary Context or human-clarification APIs.

## Acceptance and verification

1. Real request/context/native prompts distinguish Coder implementation checks from
   verification assigned to independent QA/Reviewer, with unchanged machine permissions.
2. Final-slice language preserves complete implementation and explicit Coder obligations.
3. Real native candidate finalization retains NOT_RUN and its evidence/reason; it does
   not create a QA/Review verdict. Partial slices still cannot create candidates.
4. Existing prompt, native acceptance and focused permission/lineage regressions pass.
5. Ruff, format, strict Mypy, diff check and independent review pass before commit.

## 存量数据处置 and rollback

No production SQL or old Context/Task/Plan/report changes. The fix applies only to future
provider inputs; deploy at a verified controlled boundary and recover original K1 through
public operations when necessary. Keep all draft and failure history and ordinary work
accounting. Runtime code is separate from K1 source5547815464a04991f50a2e0532d6f2f13d8daa69.
Rollback the maintenance commit and reconstruct the Host only after controlled stop;
do not remove existing artifacts or pretend any unexecuted verification passed.

# K1 planned pytest node source defect: independent QA route

## Goal

Continue the original K1 Requirement `delivery_multi_bb78e2316afca47d005384542f685174535b69db`
without replacing its frozen ProductSpec, Design, Plan, Task or accepted candidate.
The current candidate `ec178521719a9b1ce0a9d1eb97505e77fe0c3cc7` has
`tests/learning_collection/test_live_a_to_b.py`, but that file only reexports a
different test. The frozen selection
`tests/learning_collection/test_live_a_to_b.py::test_production_a_to_b_live`
is not directly declared or reexported. The public wait investigation
`operation_50a170ae6d5a95d8d84243d09ec162ed` confirmed the original QA
verifier `NOT_STARTED` and no available resolution, since the existing static
proof only detects missing files.

## Requirements

- Observe a precise, read-only candidate Git source fact for an exact frozen
  pytest function node absent as a direct definition or named reexport in a
  bounded, simple test module. Do not infer pytest's full dynamic collection.
- Keep ambiguous modules out of this route. Star imports, executable top-level
  statements, assignment, dynamic construction, malformed source or changed
  Git objects must fail closed.
- Preserve previous missing-file observation bytes and SHA, existing no-start,
  accepted artifact, current Task, queue claim and one-use engineering decision
  checks. The observation alone grants no QA verdict or role claim.
- A fresh, public `STATIC_QA_MISSING_ENTRY` decision may authorize one
  independently claimed QA source review. The only accepted output is a
  proof-bound QA `FAIL` with no test command claim; original browser, MySQL and
  live A→B checks remain `NOT_RUN`.
- Ordinary QA FAIL routing returns exact findings to ASE Coder. A subsequent
  candidate still requires full independent QA and Reviewer execution.

## Acceptance criteria

- [ ] Current K1-style import-only file yields one exact node source-gap
  observation for each frozen row, retaining all criterion IDs.
- [ ] Direct function and named alias reexport do not yield that observation.
- [ ] Dynamic/uncertain file shapes yield no static decision, with no role or
  command start.
- [ ] Existing missing-file records retain their old wire and SHA.
- [ ] Isolated public wait → decision → independent QA FAIL → Coder route is
  exercised with real owner fencing; changed candidate/claim/Plan refuses.
- [ ] Released service uses the current K1 public operation path, retaining
  original history and unchanged candidate until ASE Coder produces a successor.

## Paths and rollback

The implementation may update the candidate observation, trusted static QA
output and knowledge projection, exact related tests, generated schemas and
the linked `.trellis/spec/core/` contracts. No K1 target repository code,
private SQL, Task, verdict or sidecar bytes may be edited by the maintainer.
Before a new decision is consumed, rollback disables the extension. After
consumption, retain compatible readers and the exact decision/QA history.

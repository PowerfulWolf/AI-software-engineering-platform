# Same-source capacity resume — incremental verification

Implementation adds independent `context_capacity_resume` with exact operator PAUSE and
separate RESUME. All production deployment and original K1 approvals remain root-owned.
This implementation agent has made no production write or provider invocation.

## Executed checks

| Scope | Exact command/node | Result |
| --- | --- | --- |
| Real public Host, two owned native stops, reserved attempt 3 capacity, unchanged-source resume, independent QA/Review; ordinary no-op source update rejection | `PYTHONPATH=src python -m pytest tests/manager/test_same_base_capacity_baseline.py -q --tb=short` | 2 PASS, 48.61 s |
| Canonical regenerated and fresh static schemas, new-purpose guards, old absent/null hash compatibility | `PYTHONPATH=<absolute current src> python -m pytest tests/contracts/test_same_source_capacity_schema.py -q --tb=short` | 11 PASS, 10.88 s |
| Existing source changes/paused services/claimed capacity schema | `tests/manager/test_execution_baseline.py`, `tests/manager/test_paused_baseline_service.py`, `tests/contracts/test_context_capacity_baseline_schema.py` | 15 PASS, 92.98 s before final small v8 additions |
| Scoped binding-only Operation purpose fallback and immutable full history | `tests/web_console/test_operation_summaries.py::test_completed_binding_purpose_is_scoped_reading_metadata_without_rewriting_history` | 4 PASS; independent worker's wider scope 8 PASS |
| Version 8 running capability plus pure graft tests | `tests/web_console/test_transport.py::test_console_operation_manifest_reports_the_running_action_contract` plus first four preserved-input cases | 5 PASS, 18.25 s; two existing Starlette deprecation warnings |
| Engineering purpose and pause/start/continuation read-side labels | `tests/team_view/test_engineering_history.py` | 38 PASS, 32.70 s; independent commit `8ab415f` |
| Real public accepted progress and QA FAIL before capacity, two missing/foreign SQL publication refusals, exact PAUSE then separate RESUME, independent same-candidate QA/Review | `tests/manager/test_capacity_preserved_feedback_public.py` | 1 PASS, 40.61 s; independent commit `309ab35` |
| Pure typed candidate provenance: missing/duplicate start, missing/foreign outcome, resealed source/Context/Run/evidence, missing/foreign SQL publication, foreign step and same claim/Run | `tests/manager/test_capacity_candidate_provenance.py` | 15 PASS, 0.72 s |
| Complete pure same-source service/store/Context preservation and graft/stale/direct-RESUME cases | `tests/manager/test_capacity_baseline_preserved_inputs.py` | 7 PASS, 36.52 s |
| Historical verifier capacity, original no-start/refusal and later-claim contracts | `tests/manager/test_verifier_capacity_input.py` | 20 PASS, 10.33 s |
| Default strict mypy over changed production sources including candidate reader | Ten changed source paths, project strict settings | PASS, no issues |
| Strict mypy including new pure/public tests | Twelve changed paths with `--follow-imports=silent` | PASS, no own errors; preexisting imported test-module errors excluded |

Do not sum overlapping scopes as one test count. No full repository suite was run.

## Red-to-green finding

The real accepted-progress/QA fixture initially failed in capacity investigation (17.24 s):
the CandidateCommitSkill correctly seals candidate output SHA while its original Context
retains invocation input SHA. The historical scan incorrectly equated those facts. The fix
adds a candidate-only full original start/outcome/SQL publication proof, preserves all ordinary
source checks and rejects current same-claim output before any historical exception. The
real public fixture then passed including missing/foreign publication negatives. The pure
reader tests independently exercise resealed corruption and missing original records.

Initial final-run collection once omitted current-worktree `PYTHONPATH` and imported the
main checkout's older editable package; collection rejected before executing any test.
It was rerun with explicit current source and passed. Schema fixtures likewise use absolute
current source so subprocess generation cannot accidentally load the main editable checkout.

Final changed-file Ruff and format passed over 16 implementation/test/generator paths;
`git diff --check` passed. The independent read-only reviewer completed code/Schema/UI/history/
tests/spec review with PASS and no blocking finding. It inspected the real public feedback test,
all fifteen pure candidate-proof cases and the shared store/queue validators, without writing
implementation or duplicating the already-passed MySQL runs.

Default strict mypy passed all ten changed production sources. New pure tests passed strict mypy
with imports followed silently; the earlier default mixed-source/test command exposed existing
errors in imported `test_context_capacity_input.py` bare JsonValue indexing and
`test_production_continuation.py` optional Run ID handling. Those unrelated test modules were not
modified. New test-file typing errors were corrected before the final static PASS.

## Consumer and existing-data review

The complete contract and consumer audit are in the new v8 section of
`.trellis/spec/core/execution-baseline.md`. Store/queue use one typed plan/binding guard;
runner source resolution keeps candidate/progress active; historical Context and terminal
source readers continue using complete verified immutable store records. No source-rebind,
legacy terminal, stopped-provider or completed-output permission is widened.

No SQL migration or manual stored-fact repair is needed. Original nonterminal exact capacity
waits may prepare a new-purpose plan after a real input/config fix, inspect preserved code
and complete records, approve exact PAUSE, then separately continue the original Requirement.
New input is genuinely measured before model start; the new plan does not guarantee capacity.
Historical failed proposals and approvals are retained. Existing same-base source-rebind plans
are not silently converted or approved.

Rollback before additive record publication can revert implementation. Afterwards retain
compatible readers for new-purpose bindings/approvals, preserve all immutable history and
workspace progress, and prefer a forward fix.

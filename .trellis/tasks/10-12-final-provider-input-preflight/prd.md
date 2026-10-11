# Final provider input preflight

Goal: reject initial model input overflow before publishing DeliveryInvocationStart, using the
original Context budget and exact final provider material. Context may fit while native wrappers,
serialization, complete continuation/source material and evidence push final input over budget.

Scope: trusted preflight gate and production Dispatch factory; native/Responses initial input;
read-only continuation preview; fallback input preparation and resource cleanup. No provider or
production run, SQL repair, new retry authority, verdict, budget increase, truncation or schema
change. Main checkout remains read-only. Responses later tool-loop growth remains outside this
initial-input contract.

Acceptance:

- Existing start delegates directly to durable replay/uncertainty; preparation is skipped.
- Exact final input is compiled once before durable start and reused at actual route execution.
- Input overflow raises ContextBudgetExceeded and the existing Retry engine yields terminal
  BUDGET_EXHAUSTED; no model invocation start/outcome or fabricated stopped-execution receipt.
- Continuation preview includes the complete old patch, validates frozen authority, and writes no
  one-use admission/capture start; actual execution freshly validates equality before publication.
- Fallback preparation is pure with respect to execution authority; unused/failed resources close.
- Verifier actual FINISHED preparations remain FINISHED if the later model input cannot fit.
- Scope/policy validation failures retain their classifications.

Allowed paths: agents/model_input.py, codex_cli.py, responses.py, continuation.py, fallback.py,
candidate_binding.py; orchestration/continuation.py; manager/preflight_gate.py,
production_delivery.py, production_backend.py; focused agents/manager/orchestration unit tests;
core/delivery-preflight.md and this task record.

Validation: focused final-input, verifier-preparation, native continuation, candidate binding,
Codex, Responses, fallback, production delivery and Retry engine suites; Ruff, strict mypy and
diff check. All model/process/transport boundaries are fixture-only. Independent read-only review
is required before commit.

Results:

- Core fixture regressions: 270 passed across native/Responses/continuation/fallback, candidate
  binding, production delivery, verifier preparation, Retry engine and invocation journal.
- Known schema addition: 48 focused related checks passed; final schema and real random-launcher
  reuse additions: all 14 final-input checks passed.
- Native Python support tooling: 34 passed, 1 explicitly opt-in real local sandbox probe skipped.
- Ruff and diff check passed; strict mypy passed for all 13 changed Python source/test files.
- Independent taxonomy reviewer accepted the latest exact-schema/launcher version with no
  blocking finding; separate native reviewer checked fallback/factory/Host cleanup with no blocker.
- Native budget includes the exact platform-provided strict schema string and reuses its file;
  CLI implicit system material remains unobserved and is not claimed as provider token accounting.

Existing data: no migration or direct repair. Preserve all original start/outcome/receipt/Task and
approval bytes. Historical start without outcome still needs the existing exact engineering
investigation; terminal budget facts are not restarted or refunded by this change.

Rollback point: base 5d1ebc718f1b5ee17435615b8cdf55afefa64220. Revert the final-input commit and
reconstruct Host only when idle; retained facts and dirty worktrees remain authoritative.

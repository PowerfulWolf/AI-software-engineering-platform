# Context overflow review — 2026-09-29

## Result

Standards and Spec independent reviewers both report no remaining blocking findings.
The previous proposal incorrectly replaced frozen retrieval bodies with pointers,
breaking lexical search and snapshot-bound human resolutions. That substitution was
removed. Review also found that consultation receipts alone did not deliver READ
text to the final Coder/QA/Reviewer. Compact contexts now include verified READ evidence.

- Full approved Product/Design/Plan/approval and role-required Artifacts remain required.
- Full frozen native sources retain their source IDs, role scopes and snapshot hashes.
- Only production prompt sources paired with active retrieval are projected; all
  AGENTS.md bodies remain inline, including nested ones.
- `knowledge.reads` contains deduplicated immutable READ evidence. Both the builder
  and delivery gate validate binding, snapshot, role visibility, preceding search
  hit, citation and exact frozen chunk. Missing/replaced reads cannot pass the gate.
- Production input estimate is 128,000 (previously 64,000); accounting output reserve
  remains 4,000. Delivery and independent candidate verification share the constant.
- Timeout changes from the other session are outside this patch (that session
  committed them as `dbbeb6c` during this review).

## Verification

303 relevant tests passed across these commands:

```sh
.venv/bin/python -m pytest -q tests/knowledge tests/context tests/manager/test_joint_context_limits.py tests/manager/test_joint_contracts.py tests/manager/test_production_backend.py tests/recovery/test_verification_context_budget.py tests/orchestration/test_retry.py tests/orchestration/test_runner.py
.venv/bin/python -m pytest -q -m mysql --tb=no tests/knowledge/test_queue_mysql.py tests/manager/test_production_backend.py
```

The first run passed 299 tests; four MySQL fixture setups were denied local socket
access by the sandbox. A permitted rerun against the guarded dedicated test database
passed those four tests (10 non-MySQL tests deselected). No production data was migrated.

Ruff check, Ruff format --check and strict mypy passed on these ten changed Python files:

```text
src/ai_software_engineer/context/native.py
src/ai_software_engineer/knowledge/context_reads.py
src/ai_software_engineer/knowledge/runtime.py
src/ai_software_engineer/knowledge/delivery.py
src/ai_software_engineer/manager/production_backend.py
src/ai_software_engineer/multi_directory/production.py
tests/context/test_native_sources.py
tests/knowledge/test_prompt_projection.py
tests/manager/test_joint_context_limits.py
tests/recovery/test_verification_context_budget.py
```

New regression coverage includes full Coder→QA→Reviewer handoff, QA rework, Coder
progress, profile/baseline, body-only retrieval, original rule text in final Context,
approved resolution across reopened stores, resealed incorrect body/binding/citation,
cross-role refusal, missing/replaced READ sections and required-input/read overflow.
All successful Context sections are untruncated and token totals are checked.

## Limits, existing data and rollback

128k is an initial-input estimate using the existing characters/4 estimator, not an
actual tokenizer measurement or provider window guarantee. Local model metadata
reports 272k for configured Codex models; official documentation was unreachable.
No live model execution, service restart or frontend change was performed in this
review. Existing views therefore retain the prior durable BLOCKED state.

K1 Requirement `delivery_multi_33d30fe0776a232e31617caa9e702b915dcb4c65` and Task
`task_f887a81a33cfe89bdafd24ea01ab5ca8` remain paused. The failure predates the first
Coder Run/Context; the current terminal recovery entry requires those records.
An ordinary resume cannot safely reopen it. Before future delivery, implement the
audited successor recovery path binding the original Task/approval and the new
Context policy, approve its exact plan, then dispatch the successor through native
Coder/QA/Review. Do not reset terminal state or invent a historical Run.

This report records verification before commit. Before production resumes, rollback
consists of reverting this context-fix commit, retaining the other session's timeout commit. Once new
compact Contexts have produced live Artifacts, retain a compatible gate or roll forward;
older gates reject the new reads section. Never rewrite history to make a downgrade pass.

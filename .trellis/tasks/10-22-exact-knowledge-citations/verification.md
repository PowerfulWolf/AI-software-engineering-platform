# Verification and original K1 recovery — 2026-10-22

Status: implementation verification and independent review passed; deployment and original-K1 recovery consumption are still pending. Production K1 is not DONE.

## Original observations
Public Requirement remains delivery_multi_bb78e2316afca47d005384542f685174535b69db; Task remains task_recovery_6c7e369928a23df6e2ccf8ba32d6f816, source5547815464a04991f50a2e0532d6f2f13d8daa69.

Original main Coder run_9757269a50ad4bdab3ce3115e4bc73fa actually completed and sealed progress art_coder_07425adc2788754eecd87514cd151da8 (SHA1f9123154619a8d5cf40edb9f10c98488b150663f04a8f1a9d1e2dbac7c2f1fd). It completed step01+02; step03–08 remain. The platform automatically advanced to work_2d891a9e1a2cec543381a40bb710508f3988973b8f9e0be9f19a4c7aa3dd9947 (attempt4), whose knowledge assessment returned GAP with two invalid citations. In both, only chunk_id was changed from e8f81c8173b985ef997711280b0881d20474047cecc4da4de85d37c0a9007323 to e8f81c8173b985ef997711eb0b0881d20474047cecc4da4de85d37c0a9007323. Other citation fields agree. Exact READ refusal is correct.

Independent typed rederivation validates all20 search/READ records,16 READ citations, original Context/request/route receipts and outcome9c47ecb0fe989a2ce2d8c0c3cfa4cd370a950d6f5558c39baf8cbb3f1244008b. Observation4434f403336ef081dda52d25564a536f18c824f4dcdc0de56a808e535409d438 is unchanged. Root additionally rederived that actual legacy production observation using the new maintenance code: full historical read passed,16 citations, identical identity. No raw provider logs or secret values were inspected or printed. Full rederivation reads complete Context/evidence; this audit excludes their document bodies.

## Exact recovery candidate, not consumption
- Parent checkpoint a56634374e3f2287cd658f8b90fe210e718dee315812712e6e2089c28f7678bb.
- Inspect operation_82e0be71b892da7d4a10bf623d924dc5 SUCCEEDED, no missing facts.
- Handle operation_03278d699afb74ccc558e8793df2e6d3 SUCCEEDED/NEEDS_AUTHORIZATION.
- Exact Handle proof aca1629171c912765b037e86576bfb7d72a24c610544db123efb36b70be97202.
- Current complete draft49e4dd92c651f2dcddd22ba6653ae8705532cf2e3912ebd311cf74789ee22db0:21 paths,2982 inventory entries; inventory8867381d93ae77b66146a1807c5f0ca5bd1d9640a826359f21ff1051c3c2f7dc; captureebe687e815dc80711013f79ecb9c57b643c1640662b6af473a03225c42c2721b.

An independent read-only researcher reopened the typed ConsoleOperation, current draft, progress store, invocation start/outcome, capture start/stop and both Contexts. All agree on same Task/source/permissions, latest accepted progress and actual completed rc0 original main execution. This is static lineage verification, not current process/inventory approval or candidate acceptance.

At2026-10-22T06:12:32.600589Z a SELECT-only consistent read found Task IMPLEMENTING/revision8, attempts4/work_attempt4, no active claims and original work WAITING_DEPENDENCY. Task.max_attempts40 includes transient execution identities; ordinary retry_policy.max_work_attempts is10, not40. No budget was changed or refunded. SQL and final live inventory freshness must still be rechecked by public Resolve.

## Red/green and current checks
The actual consultation transport admitted a valid citation and also admitted the two-character typo/cross-object tuple under the old static schema. Four raw/strict cases failed with DID NOT RAISE before the fix and passed afterwards. New schema tests additionally cover all six citation fields, complete duplicates, domain-schema immutability and empty READ. New HTTP tests preserve old static and new exact request formats and raw record bytes while provider noncompliance still produces CLAIM_WITHOUT_READ.

Full focused results, code review, controlled deployment and actual public recovery outcomes will be appended only after execution. A fixture success or a successful recovery Operation is not K1 delivery success.

## 存量数据处置
No SQL migration, historical citation repair, Task reset, verdict rewrite, source update or product reapproval. Keep original wait/outcome/event bytes. After verified idle controlled deployment, use the current exact Handle proof and explicit delegated ENGINEERING Resolve; it must freshly check complete bytes/modes/index/ignored inventory, original inactivity, latest Task and frozen work limit. Preserve the same public Requirement and source and consume one ordinary allowance exactly once. Any new genuine prerequisite stays a typed wait; cannot use fixture or Context injection to prove real browser/A-to-B acceptance.

## Rollback
Code reference b2c634409dd145639f2147600ee792e8175e04f9. Controlled stop is mandatory before replacement. Once any new exact request is sealed, retain compatible request rederivation even when disabling new emission. Consumed engineering decisions and old failed results remain immutable; do not erase decisions, reset SQL counters or replay approvals to simulate rollback.

## Completed verification before deployment

Final focused command (maintenance cwd, normal approved fixture process access):

```sh
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider tests/knowledge/test_assessment_schema.py tests/knowledge/test_assessment_rejection.py tests/knowledge/test_consultation.py tests/knowledge/test_invocation_native.py tests/knowledge/test_invocation_receipts.py tests/knowledge/test_invocation_pause.py tests/knowledge/test_schema_parity.py tests/knowledge/test_delivery_context.py tests/knowledge/test_delivery_requirement_scope.py
```

Result: **235 passed in21.47s**, no skips. This includes13 schema cases and2 old-static/new-exact HTTP rederivation cases; subsets are not additional tests. The first sandbox-only broad run failed native process ownership observation; the normally approved rerun used the same unchanged command/code and passed. Fixtures used no production SQL/provider and do not establish K1 business acceptance.

Five changed Python files passed `python -m ruff check --no-cache`, `python -m ruff format --check --no-cache`, and `MYPYPATH=src python -m mypy --strict --no-incremental --cache-dir=/tmp/ase-exact-read-mypy`; `git diff --check` passed. Scope: knowledge/assessment_validation.py, agents.py, assessment_rejection.py, tests/knowledge/test_assessment_schema.py and test_assessment_rejection.py.

Independent read-only review found no actionable code/spec findings. Reviewer independently ran13 schema tests and scoped Ruff, checked raw/strict JSON Schema validity and verified complete-tuple/empty READ and exact two-request historical compatibility. Original static domain schemas and global prompts remain unchanged; no regeneration or database migration is required. The maintenance diff changes3 production files and2 test files only, plus the explicit task/spec records.

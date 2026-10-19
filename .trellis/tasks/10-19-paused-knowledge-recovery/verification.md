# Paused knowledge recovery verification

## Exact production target before maintenance

The original K1 Task is `task_recovery_711a755e5852a52346876a7b07376311`, native Requirement
`delivery_c833c3235d0bb73adba67937d16ea66c`, joint Requirement
`delivery_multi_bb78e2316afca47d005384542f685174535b69db` in
`project_ai-project_034252eb3595`. At the prior checked boundary it is IMPLEMENTING,
attempt 5/revision 11, with three accepted Coder slices and no candidate/QA/Review.
Run5 WorkItem `work_210001bf077c1479ae8b9381fe384beda4762e392a960f4db0d6760cd3a93ddd`
waits after its released `lease_87978ab84d6f319f867b92fa`. The old knowledge outcome
remains FAILED/SERVICE_PAUSED with empty executions and UNKNOWN historical transport.

Keep approved source `fa3589a2251ed19a54bdd8848bad82ab4d7c61ae`, all accepted progress,
and the inherited 225678-byte patch with SHA-256
`26710e71e0bf31c26b61b35daa749c4575671fbc7d9e2f4aff8f23c4a9c1cfb7`.
Maintenance source and deployed main revision are separate from that approved delivery input.

The final pre-deployment SELECT-only snapshot at `2026-10-19T10:51:40Z` is
`/tmp/ase-k1-stage-snapshot-20261019-21.json`, SHA-256
`049022c388ba5e4659ea8d5ec5a428064a15d87ce79e06ea407323c8987f08a9`.
It confirms the same Task state, five released claims, three formally accepted progress
artifacts and no candidate/QA/Review. Public summary and exact-locator Task detail agree:
the old waiting WorkItem, parent checkpoint and Task intent/revision remain unchanged.

## Reproduction and focused checks

Use the main checkout `.venv/bin/python`, `PYTHONPATH=src`/`MYPYPATH=src`, from the maintenance
worktree. Provider and independent role ports in regression fixtures are deterministic fakes;
none of their verdicts or DONE states is a production K1 result.

- Producer verification is recorded in `producer-verification.md`: real guard and journal
  positives/negatives **16 passed**, existing native knowledge regression **35 passed** in the
  authorized subprocess environment. Old empty/generic errors cannot create a receipt.
- Consumer verification is recorded in `consumer-verification.md`: new consumer/purge/crash
  replay **15 passed**, existing wait regression **54 passed**, exact isolated MySQL consumption
  and refusal **7 passed**, full forward public Host composition **1 passed / 7.92s**. The last
  fixture verifies same Task/attempt, new dispatch/claim/Run/Context, unchanged old bytes and
  independent QA/Review of the same candidate. Its owned registry ends at zero.
- The stored legacy public Host path initially passed the complete exact PAUSE → separate
  RESUME → fresh Coder candidate → independent QA/Review path in **20.21s**. Additional exact
  replay, scope and historical-reader refusal checks are recorded by the legacy implementer.
- Independent store-reader finding reproduced with **4 failed / 18.96s** on the missing guard:
  rehashed foreign proof was accepted by authority/reopen/standalone Context, and Context used
  an incorrect source-update description. After reusing the pure exact binding guard, all four
  pass; the Context retains UNKNOWN history, ordinary work accounting and the complete patch.
- Final domain/published-schema/fresh-regeneration checks after the new guard corrections:
  `pytest tests/contracts/test_repair_schema_generation.py tests/domain/test_knowledge_preparation_pause_schema.py -q`
  → **46 passed / 5.78s**. Includes no-target proposal, explicit PAUSE confirmation, null/omitted
  isolation proof, mixed receipt/proof refusal and old absent-optional wire compatibility.
- `ruff check src tests scripts` passes. `mypy src` passes for all **393** production source
  files. `uv --cache-dir /tmp/ase-paused-knowledge-uv-cache-20261019 lock --check --offline`
  resolves the existing **55** locked packages without changes. Offline source/wheel build
  succeeds in `/tmp/ase-paused-knowledge-build-20261019`. `git diff --check` passes.
- Shared PAUSE / separate RESUME MySQL regression:
  `pytest tests/work_queue/test_baseline_pause_mysql.py -q --tb=short`
  → **38 passed / 290.55s**. Its post-test SELECT-only check again confirms all 13
  mutable tables empty and the authority lock available NOWAIT, then rolled back.
- Final legacy public Host recovery and native-process checks → **2 passed / 19.81s**;
  the final legacy focused group → **85 passed, 2 deselected / 75.88s**. These include
  exclusive current confirmation, exact replay, preserved bytes, fresh claim and independent
  fixture QA/Review, without changing any production fact.
- Final narrow Schema inventory / child-import regression:
  **3 failed** before the correction, then **12 passed / 9.20s**. Three-file strict Mypy,
  Ruff and format checks pass. The child explicitly imports the current checkout's absolute
  `src` while retaining its otherwise isolated environment. The exact stop-embedding set
  includes both the existing stopped-failure schema and the new isolation schema; missing,
  extra or replacement entries remain rejected before writes.

## Independent review and baseline debt

Forward review report `/tmp/ase-paused-knowledge-forward-independent-review-20261019.json`
has SHA-256 `ccb8da1fa66bcac2466e9c347158e617c40a2c1c730463195ee8369e3b83563b`.
It covers the report-bound forward snapshot; later legacy/store/generator corrections require
their separate final increment. Independent checks also validate all **176** schemas and
their local reference closure. Propose's existing no-target guard is explicitly extended for
the one new purpose; its older purpose branches keep their previous semantics.

Final legacy/store/queue/schema independent review:
`/tmp/ase-paused-knowledge-legacy-queue-schema-independent-review-20261019.json`, SHA-256
`bad943066219ec679ce1d1ca6c84a525d91e16854f5623501af0ac244c2c2343`, **PASS**, no unresolved
P1/P2; independently **82 passed / 29.99s** and regeneration **30 passed / 5.66s**.
The final three-file increment is independently reviewed in
`/tmp/ase-schema-fixture-sync-independent-review-20261019.json`, SHA-256
`7315055da91c0b9851d5f13d511085cf16c8ebdda7a1e7c7a385a8732cd19d44`, **PASS**, independently
**12 passed / 7.91s**. A final hash comparison finds all **53 changed material source,
test, script and Schema files** covered by these reports and unchanged since their latest
review. These are platform maintenance reviews, not production K1 role verdicts.
Byte-identical copies of all three independently authored reports are retained under this
task's `reviews/` directory, with the same hashes, so the organization retains the review
evidence after temporary files are removed.

Full `mypy src tests` was measured on both main e309f0b and the maintenance tree. Main already
has **227** test diagnostics. The first maintenance pass added two new test annotations,
which their owner corrected; production source remained clean. Do not report the whole old
test tree as strict-Mypy clean. Likewise the unchanged `tests/projection/test_projector.py`
has a pre-existing formatting difference; changed files must pass their format check.

The broad non-MySQL command `pytest -q -m 'not mysql' --tb=short` completed with
**6777 passed, 37 failed, 27 skipped, 421 deselected, 2 warnings / 3052.99s**. Its log
`/tmp/ase-paused-knowledge-full-nonmysql-20261019.log` has SHA-256
`31773fd440a749e9e56f537dbd9944c82c2def67aeac0bb074be6f07220893cc`.
It began before final review corrections and retained the earlier imported source. Four
failures are corrected and covered by final focused checks: the appended foreign knowledge
claim refusal, the child-process current-source import, and two exact stop-schema inventory
cases. The remaining 33 failures were compared on main e309f0b and maintenance; they fail
on both. The full suite is **not** reported as passing.

The existing failures include old assertion codes/read counters/error wording, incomplete
typed fixtures (journal, capacity input, accepted artifact root or settlement), old role-less
product-client setup, original schema-equality/order assertions, and existing command-stop or
verifier-route expectations. In particular, the continuation static JSON Schema accepts one
invalid cause/stop combination that its typed Python model rejects. This is a real pre-existing
published-schema contract debt, not merely a fixture issue; the runtime remains fail-closed,
and this repair does not relax that negative test or its typed validation. The two warnings
are third-party Starlette/httpx and AnyIO deprecations. Detailed independent per-case attribution
is retained with the task's review evidence when finalized.
The finalized independent attribution is `reviews/nonmysql-triage.json`, SHA-256
`57c8490ca4bb5a3cd198333ba63383ade3574ae015123ccb2aab13c07e4b02ea`; all 37 cases are
accounted for. The final appended-foreign-claim refusal was independently rerun:
**1 passed / 19.94s**. Combined with the final independent 12-case increment, none of the
four earlier-snapshot failures remains unresolved. Of the original failures, 35 already
existed on main and two were introduced during implementation; the final four corrections
also fix two existing exact-inventory failures.

## Isolation and permissions

Only the identity-checked dedicated test database is used in MySQL tests, serially by one
test process at a time. Its guard refuses production-like database names. Post-test records
confirm all 13 mutable facts tables empty, no active owned process or lease, and successful
NOWAIT authority-lock acquisition followed by rollback. No DSN or key is printed or archived.
Temporary subprocess and local database tests run under the user's explicit authorization;
an automatic approval capacity timeout is not a test result or permission to bypass checks.

## Stored-data disposition and rollback

No production SQL, old outcome, stop, role verdict or K1 dirty file has been edited by this
maintenance implementation. Recheck exact current production facts, deploy only at the
official controlled idle/exit boundary, and use the public baseline proposal and precise
current ENGINEERING decision. That decision retains historical UNKNOWN; it does not reuse
the unrelated October 14 local-execution declaration. Execute must leave a new PAUSED
ordinary-work successor before a separate exact RESUME can claim fresh work.

Append actual public operation/plan/authorization/binding IDs and before/after checks after
production execution. If any current containment fact is insufficient, keep the existing
wait and report that concrete blocker. Rollback retains every new immutable record and the
paused successor; it never reverses counters, deletes history or dispatches the old claim.

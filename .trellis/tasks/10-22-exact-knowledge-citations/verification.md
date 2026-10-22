# Verification and original K1 recovery — 2026-10-22

Status: platform repair passed verification and independent review, was pushed to main and deployed through controlled replacement. The exact original-K1 recovery decision was sealed and consumed. The subsequent attempt6 main Coder outcome is now sealed as coder-progress. At the final recorded public snapshot, attempt7 was in KNOWLEDGE_PREPARATION. Production K1 is not DONE; the progress report is not a candidate or independent QA acceptance.

## Original observations
Public Requirement remains delivery_multi_bb78e2316afca47d005384542f685174535b69db; Task remains task_recovery_6c7e369928a23df6e2ccf8ba32d6f816, source5547815464a04991f50a2e0532d6f2f13d8daa69.

Original main Coder run_9757269a50ad4bdab3ce3115e4bc73fa actually completed and sealed progress art_coder_07425adc2788754eecd87514cd151da8 (SHA1f9123154619a8d5cf40edb9f10c98488b150663f04a8f1a9d1e2dbac7c2f1fd). It completed step01+02; step03–08 remain. The platform automatically advanced to work_2d891a9e1a2cec543381a40bb710508f3988973b8f9e0be9f19a4c7aa3dd9947 (attempt4), whose knowledge assessment returned GAP with two invalid citations. In both, only chunk_id was changed from e8f81c8173b985ef997711280b0881d20474047cecc4da4de85d37c0a9007323 to e8f81c8173b985ef997711eb0b0881d20474047cecc4da4de85d37c0a9007323. Other citation fields agree. Exact READ refusal is correct.

Independent typed rederivation validates all20 search/READ records,16 READ citations, original Context/request/route receipts and outcome9c47ecb0fe989a2ce2d8c0c3cfa4cd370a950d6f5558c39baf8cbb3f1244008b. Observation4434f403336ef081dda52d25564a536f18c824f4dcdc0de56a808e535409d438 is unchanged. Root additionally rederived that actual legacy production observation using the new maintenance code: full historical read passed,16 citations, identical identity. No raw provider logs or secret values were inspected or printed. Full rederivation reads complete Context/evidence; this audit excludes their document bodies.

## Original recovery preparation (before deployment and consumption)
- Parent checkpoint a56634374e3f2287cd658f8b90fe210e718dee315812712e6e2089c28f7678bb.
- Inspect operation_82e0be71b892da7d4a10bf623d924dc5 SUCCEEDED, no missing facts.
- Handle operation_03278d699afb74ccc558e8793df2e6d3 SUCCEEDED/NEEDS_AUTHORIZATION.
- Exact Handle proof aca1629171c912765b037e86576bfb7d72a24c610544db123efb36b70be97202.
- Current complete draft49e4dd92c651f2dcddd22ba6653ae8705532cf2e3912ebd311cf74789ee22db0:21 paths,2982 inventory entries; inventory8867381d93ae77b66146a1807c5f0ca5bd1d9640a826359f21ff1051c3c2f7dc; captureebe687e815dc80711013f79ecb9c57b643c1640662b6af473a03225c42c2721b.

An independent read-only researcher reopened the typed ConsoleOperation, current draft, progress store, invocation start/outcome, capture start/stop and both Contexts. All agree on same Task/source/permissions, latest accepted progress and actual completed rc0 original main execution. This is static lineage verification, not current process/inventory approval or candidate acceptance.

At2026-10-22T06:12:32.600589Z a SELECT-only consistent read found Task IMPLEMENTING/revision8, attempts4/work_attempt4, no active claims and original work WAITING_DEPENDENCY. Task.max_attempts40 includes transient execution identities; ordinary retry_policy.max_work_attempts is10, not40. No budget was changed or refunded. SQL and final live inventory freshness must still be rechecked by public Resolve.

## Red/green and current checks
The actual consultation transport admitted a valid citation and also admitted the two-character typo/cross-object tuple under the old static schema. Four raw/strict cases failed with DID NOT RAISE before the fix and passed afterwards. New schema tests additionally cover all six citation fields, complete duplicates, domain-schema immutability and empty READ. New HTTP tests preserve old static and new exact request formats and raw record bytes while provider noncompliance still produces CLAIM_WITHOUT_READ.

Completed checks and actual deployment/recovery observations follow below. A fixture success, consumed engineering decision or successful Operation does not establish K1 delivery success.

## 存量数据处置
No SQL migration, historical citation repair, Task reset, verdict rewrite, source update or product reapproval. Keep original wait/outcome/event bytes. After verified idle controlled deployment, the public exact Handle and delegated ENGINEERING Resolve rechecked complete bytes/modes/index/ignored inventory, original inactivity, latest Task and frozen work limit. The consumed decision preserved the same public Requirement/source and charged one ordinary allowance exactly once, as detailed below. Any new genuine prerequisite stays a typed wait; cannot use fixture or Context injection to prove real browser/A-to-B acceptance.

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


## Actual controlled deployment

Runtime commit `ec9c61c1508bf8e2904696a8160f4931e4fd0c87` was integrated into main and pushed.
The runtime update does not change K1's approved source, ProductSpec, Plan or native rules.

- Official controlled shutdown request: `console_shutdown_ef28d2c71a005dd27f785d71fb2ac2ac`.
- Old service PID `47254` reached READY at `2026-10-22T06:25:43.718469Z`; actual process
  exit was separately confirmed. READY alone is not proof of exit.
- New service PID `45506`, instance `console_instance_0e384478072e65dd81ebb06bde8b7be6`,
  started at `2026-10-22T06:27:17.009503Z` and loaded the runtime commit above.
- No recurring automation was created. Read-only foreground observations do not schedule
  future execution or assert completion after the observation window.

## Consumed exact recovery and existing data

The upgraded service obtained a fresh public Handle:

- Operation `operation_a4a5c3467b1285545f7293e517e847b4`: SUCCEEDED,
  handling `NEEDS_AUTHORIZATION`, `missing=[]`.
- Exact investigation proof:
  `aca1629171c912765b037e86576bfb7d72a24c610544db123efb36b70be97202`.
- The current full draft remained bound to its21 paths and complete2982-entry inventory;
  the old malformed assessment and all earlier progress remain intact.

Under the user's delegated engineering authority, public Resolve
`operation_796e281c8394bf6caca210ea4fe1beca` sealed and consumed decision
`65fa1a02abf60bd8b969272d8639e911565fd200ab128f31a7428b598d0607df`.
Its authorization source is `engineering_operator_decision`, trusted principal
`operator:local-console` with ENGINEERING duty. The Operation was still RUNNING at the
latest observation because it continued real delivery; decision consumption was verified
separately and is not inferred from final Operation success.

A consistent SELECT-only snapshot at `2026-10-22T06:33:33.195022Z` confirmed:

- Original wait `work_2d891a9e1a2cec543381a40bb710508f3988973b8f9e0be9f19a4c7aa3dd9947`
  is CLOSED; new same-Task successor
  `work_65fa1a02abf60bd8b969272d8639e911565fd200ab128f31a7428b598d0607df`
  is attempt5 with a real active claim.
- Ordinary work increased once from4 to5. Frozen `max_work_attempts=10` and execution
  `max_attempts=40` are unchanged; work budget was not exhausted.
- Task remained IMPLEMENTING, revision8, source
  `5547815464a04991f50a2e0532d6f2f13d8daa69`.
- SQL was not manually changed. No old result, citation, approval, claim, budget or role
  verdict was rewritten or refunded.

## Subsequent provider failure and automatic continuation

Attempt5 main Coder did not start. Its knowledge intent returned, but assessment outcome
`7c718037e29f94f131d7b54dff13361244fd6a121f8bcecaa5dd5d4580773530`
failed after an HTTP route504 and native fallback rc1. The fallback's specific cause is
UNKNOWN; the typed `PROVIDER_UNAVAILABLE` classification alone does not prove the native
fallback's underlying cause was transient. Preserve the actual failure/route history rather
than reclassifying it as the earlier citation error.

The platform subsequently created attempt6 under the same public Requirement and Task:

- WorkItem `work_9886044b2a3e2f7bb36590e71b256bbf8f4f7bdd7085f69189a785a105193a00`.
- Fresh knowledge Run `run_knowledge_ea26710244b0b2774d4213042e92132d` and real lease
  `lease_ea30d12010da12763d575148`.
- Intent RETURNED outcome:
  `8b0eaba9fd2e92e7552c9a8ab01f9f001b66d4970a2fe2b07b3505e8973ecd9f`.
- Assessment RETURNED outcome:
  `3c65391c3b21b17734a8fbb811c4311641fb6e5e1732dc692b2ed3d0cee82197`.

The actual new assessment request independently reconstructed to exact-schema digest
`28bebf678922162d97e2156f2f55c67fe648419fe879232c672c756a2773e1ca`.
Its original-static-schema reconstruction is
`a20ffae2ae80fe26f5c9e0f37bdb80eb5a9165664a30fd40b9b081532c1c2486`;
these differ. This verifies real prospective exact-schema emission as well as historical
static compatibility; it does not imply candidate or acceptance success.

## Historical main-execution observations before outcome sealing

A fresh main Coder actually started at `2026-10-22T06:44:11.687305Z`:

- Run `run_c6ea02e017d44ebf91ad36e69f10a8cc`, attempt6.
- Context `ctx_bd2fbde627ecd9c7ce61aaa5cb5f872dc0fb416a21bbcc589aa0fc9b805e076c`.
- Start SHA `0d6fe70fb60d82c4854e58bbeec2f2522573606dce2d1809c63eff849283389b`.
- Source remains `5547815464a04991f50a2e0532d6f2f13d8daa69`.

At `2026-10-22T07:06:41Z`, its real lease heartbeat was valid in ROLE_EXECUTION.
The typed start proves actual invocation startup; a valid lease heartbeat proves lease
activity, not current model/tool progress, which remains UNKNOWN.
At that observation, the main invocation had a start and no outcome. The previously accepted
progress completes step01 and step02 only; step03 through step08 require new accepted
artifacts. K1 has no newly verified candidate, QA PASS or Review APPROVE at this observation.
A subsequent SELECT-only consistent snapshot at `2026-10-22T07:10:18.713115Z` confirmed
the same Task in IMPLEMENTING/revision8 with attempts6, ordinary work_attempt5,
max_work_attempts10 and max_attempts40, unchanged base `5547815464a04991f50a2e0532d6f2f13d8daa69`,
and the same attempt6 WorkItem RUNNING with its lease ACTIVE (heartbeat
`2026-10-22T07:10:12.212804Z`); this automatic transient continuation did not consume
another ordinary work allowance.
The remaining real browser/A-to-B verification and independent same-candidate QA/Review
must still run. Their missing prerequisites must remain formal engineering waits; fixture
results and restored execution cannot substitute for acceptance.

## Sealed attempt6 progress and final recorded public snapshot

At `2026-10-22T07:16:27Z`, root independently validated a typed
`DeliveryInvocationOutcome` for main Run `run_c6ea02e017d44ebf91ad36e69f10a8cc`.
The invocation result is SUCCEEDED and references coder-progress, not an implementation
candidate:

- Outcome SHA `b14a5004826d8faeab747a8231f3c6b3d5c3cc23985bd7f4364da2fc27d5cebc`.
- Artifact `art_coder_567173b6f4ad7d784797f10003a9543b`, SHA
  `2a5d2399f84279d62ac066c063152605584355e2ffaebf08389a90d23f4b8548`.
- The report declares25 changed_files, completed step01/step02 and remaining step03–step08.
- It reports unit tests, Ruff, strict Mypy and formatting PASS, while real
  `tests/learning_collection/test_source_stream_mysql.py` is NOT_RUN because the sandbox
  could not isolate SQL. These are Coder report statements, not independent QA acceptance.

The public snapshot in `/tmp/ase-k1-after-progress6-snapshot-20261022.json`, as of
`2026-10-22T07:18:15.909381Z`, independently shows the same Requirement DELIVERING and
the same Task IMPLEMENTING/revision11. Attempt6 WorkItem
`work_9886044b2a3e2f7bb36590e71b256bbf8f4f7bdd7085f69189a785a105193a00` is CLOSED.
Successor attempt7 WorkItem
`work_aa53360c6364ce1f26ffac2dd4acdbbda295d8b21a903d1d07785b097dea9336`
is RUNNING in KNOWLEDGE_PREPARATION, with a valid lease heartbeat recorded at
`2026-10-22T07:18:02.554729Z`. This identifies knowledge preparation, not a new main
Coder start or current model/tool progress. The earlier no-outcome observations remain
historical and are superseded by the sealed attempt6 outcome above.

There is still no newly verified candidate, QA PASS, Review APPROVE or K1 DONE.
The actual isolated MySQL, real browser/A-to-B checks and independent same-candidate
QA/Review remain required. No further live observation is asserted by this frozen record.

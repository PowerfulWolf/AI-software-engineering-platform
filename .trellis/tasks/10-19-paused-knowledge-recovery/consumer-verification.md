# Forward knowledge pause consumer verification

This maintenance implementation does not read or mutate production K1 SQL, Task,
worktree, budget, outcome or approval. It consumes only a newly sealed positive
pre-admission refusal or the existing exact native admission-closed pair. A legacy
`FAILED / SERVICE_PAUSED / executions=[]` remains insufficient.

## Change and executable checks

- `manager/knowledge_preparation_pause.py` rereads the independent pause index,
  intent/outcome/receipt, original claim, complete persisted Context and frozen
  snapshot, Requirement scopes and current Task/source/checkpoint. It checks every
  claim for main/native/route/artifact contradictions. Another phase of the same
  claim must have complete independent executions and have RETURNED before refusal.
- `manager/delivery_wait.py` exposes the typed proof only through existing exact
  inspect/resolve operations. An unconsumed sealed decision reopens its file proof
  after a crash; a consumed later generation goes to existing SQL idempotency.
- `work_queue/execution_store.py` checks the original claim digest and current
  waiting dispatch, frozen task/source/role/scope, no active task claim, no accepted
  current output or completed current work. It changes only the same WorkItem to
  READY at dispatch+1, keeping Task attempt and all budgets/events untouched.
- `multi_directory/purge_knowledge.py` recognizes new index/raw namespaces. A raw
  receipt left before outcome publication is selected only by a matching owned
  intent; foreign lanes and unbound raw receipts cannot be swept by directory name.

Commands use the main checkout's virtualenv Python and `PYTHONPATH=src` from the
maintenance checkout, unless a separate value is stated.

1. Initial precise positive consumer red test:
   `pytest -q tests/manager/test_knowledge_preparation_pause_consumer.py::test_positive_pause_has_exact_public_proof_and_same_attempt_decision`
   → **1 failed in 0.97s**, after canonical Context/claim construction; expected
   `RESUME_UNINVOKED` remained absent on the old collector path.
2. Consumer + cleanup tests:
   `pytest -q tests/manager/test_knowledge_preparation_pause_consumer.py tests/manager/test_knowledge_pause_purge.py`
   → **15 passed in 4.05s**. Includes raw/native-pair positives, public service
   resolve, missing index/receipt/Context/snapshot, legacy empty executions,
   aliased main Run, pending/FAILED prior phase, complete RETURNED prior phase,
   unconsumed crash replay and owned orphan/foreign cleanup.
3. Isolated SQL tests:
   `pytest -q tests/work_queue/test_knowledge_pause_mysql.py --tb=short`
   → **7 passed in 2.51s**. Uses the inherited dedicated `ASE_TEST_MYSQL_DSN`
   and repository test identity guard. Exact positive decision is consumed once;
   real Dispatcher issues a fresh lease at the same attempt, dispatch+1. Wrong
   lease/digest/dispatch/attempt/scope and absent proof refuse with no mutation.
4. Post-SQL read-only cleanup check:
   `/tmp/ase-knowledge-pause-mysql-cleanup-check.json` proves all 13 mutable test
   tables empty and `work_queue_authority_lock` acquired NOWAIT and rolled back.
5. Existing wait regression: the initial sandbox run had 9 existing native fixture
   setup failures at trusted `owned_spawn` process-identity inspection (61 other
   cases passed in the combined run). The authorized outside-sandbox rerun
   `pytest -q tests/manager/test_delivery_wait.py --tb=short`
   → **54 passed in 54.72s**; no production services or workspaces are involved.
6. Ruff check, Ruff format check and strict Mypy pass over the four owned source
   files and four consumer/queue/cleanup/public test files.

## Full public Host composition

`tests/manager/test_knowledge_pause_public.py` uses a real current Host guard, full
knowledge Journal, public Host inspect/resolve, transactional Dispatcher and fresh
claim/Run/Context before independent fixture QA/Review. No receipt is constructed
by that test. Its provider/role adapter ports are deterministic fixtures; a fixture
DONE is not evidence of K1 completion.

`pytest -q tests/manager/test_knowledge_pause_public.py --tb=short` → **1 passed
in 8.75s** on the initial complete public composition. After adding a real
`HostOwnedProcessRegistry` around the whole test, the final same command → **1
passed in 7.92s**, including registry snapshot=0 and `require_stopped`, no active
leases, unchanged original knowledge bytes, original Task attempt and retry
counters, fresh claim/Run/Context and QA/Review bound to the delivered candidate.
Ruff/format/strict Mypy pass for the final file. The dedicated SQL test window was
serially handed over after the separate legacy recovery test released it.
Post-test read-only checks again confirmed all 13 mutable tables empty and the
queue authority lock acquired NOWAIT then rolled back; the DB window was released.

## Stored-data disposition and rollback

This forward consumer cannot recover the already existing K1 missing-fact outcome.
The task's separately reviewed engineering isolation path owns that recovery and
must keep the old unknown/empty outcome and all drafts unchanged. Reverting this
consumer code must retain new typed readers and immutable pause records; deploy
only through the verified controlled stopped boundary. No database migration,
counter refund, Task reset or historical verdict rewrite is part of this change.

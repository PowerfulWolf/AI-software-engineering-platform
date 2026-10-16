# Verification and production treatment — in progress

## Exact observation

Independent Run6 audit SHA4037b910cdff394806b07691c81d698f2e423b2f52266fdfdc7424bf42bca6f7
retains invocation/admission/capture-start identity, source774e0a6, Task revision8/attempt6
and the genuine failed native stop at 06:00:39.964648Z. Stop SHA
dcb6aad8bf01eee6fb4ce2d98aef415af600c61eb977029dc56c5b7649eb59a3 has returncode-15,
cause=null and output_present=false; owned-session proof SHA
2f3d284ef0e1d8e1dbd15157f60f46987fa762f800c58194a3b1cbf208cbbe1f is valid.
This was not the local30-minute limit and does not establish a provider failure.

No Run6 route, invocation outcome, receipt, accepted progress or verdict exists. SQL report
SHAdc07f9c7ab8280dccf85e02e7981c148b024f54b4675f3695bd78284b0efb054 confirms only
ENQUEUED→CLAIMED→STARTED, without WAIT/RELEASE; last heartbeat06:00:36 expired06:01:36.
Original195 immutable files remain unchanged. HANDLE Operation success references the prior
Run5 handling, not a Run6 outcome. The initial OS observation cause is unrecorded.

## Feedback loop

The author first ran the new regressions against unchanged production code: 3 failed,
1 passed in3.63s. Failures reproduce real native active-observation raw uncertainty and
real claimed supervisor raw-adapter/outer-finalization uncertainty. The ordinary RuntimeError
negative already passes. The minimal production fix then passes all4 cases in4.78s;
explicit DictCursor typing was followed by3 MySQL cases passing in4.83s.

Related native/output, invocation-journal, ownership and real worker MySQL suites:
`PYTHONPATH=src <main-venv>/python -m pytest -q --tb=short
tests/agents/test_native_output_bounds.py tests/agents/test_codex_cli.py
tests/work_queue/test_owned_execution.py tests/work_queue/test_invocation_journal.py
tests/work_queue/test_worker_mysql.py`: 127 passed in82.78s. The new tests check real stop/EOF,
honest observer publication, WAITING_DEPENDENCY/EXECUTION_UNCERTAIN, real RELEASED claim with
ended_at, unchanged Task/events/artifacts/budget and no outcome or replayed role call.

Independent read-only review finds no blocking issue. Its separate four-case real native/MySQL
run passes in5.20s; affected-file strict Mypy, Ruff/format and diff checks pass. Source changes
are limited to native typed normalization and the existing supervisor uncertainty catch.
This does not establish the original OS trigger or recover the old parent checkpoint.

## 存量数据处置

No production SQL or historical facts have been edited. The parent/native delivery checkpoints
are BLOCKED/INVARIANT_VIOLATION although Task remains IMPLEMENTING. Therefore an ordinary
Continue cannot be assumed to reach Dispatcher. Verify and test the existing public
stopped_execution_rescue route and any required exact current-claim lifecycle before deployment.
Its real empty-session proof may establish stopped execution; absent cause must remain absent.
Do not create a transient receipt or refund. Native candidate and independent QA/Review remain
required. Deployment and actual public recovery have not yet occurred for this fix.

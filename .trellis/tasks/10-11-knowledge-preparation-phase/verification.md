# Incremental verification

## Change and evidence

The read projection now distinguishes current knowledge preparation, a trusted
main-role invocation start, and local result saving. Task, Requirement and activity
presentation reuse the same Chinese backend reason. A valid live claim without
fine receipts remains neutral about whether the main call has started.

The source resolver uses the exact hashed queue step and validated pre-claim local
baseline overlay. It does not assume Task.base_ref is current after rebind. Queue
events have no historical SHA field; their typed identity/detail is checked against
the exact claim and independently hashed baseline consumption. Unsupported
inherited epochs remain neutral. The pure overlay extraction leaves writer-only
inherited authorization in place.

The bounded file reader rejects unsafe ancestry, symlink/FIFO/oversized files,
bad hashes, foreign lane identities and overcount before payload reads. Knowledge
outcomes must retain independent content-addressed execution receipts. Fixtures
compare the file inventory before and after projection to prove no writes.

## Results

The main incremental Python command passed **81 tests in 13.34 seconds**:

```sh
.venv/bin/python -m pytest \
  tests/team_view/test_knowledge_preparation_phase.py \
  tests/team_view/test_knowledge_phase_source.py \
  tests/team_view/test_knowledge_phase_queue.py \
  tests/team_view/test_product_execution.py \
  tests/team_view/test_snapshot_schema.py \
  tests/contracts/test_baseline_pause_schema.py \
  -m 'not mysql' -q
```

Final DOM verification after the neutral fallback and exact harness correction
passed **108 tests in 0.24 seconds**:

```sh
node --test \
  tests/team_view/product-execution.test.cjs \
  tests/team_view/delivery-status.test.cjs \
  tests/team_view/operation-progress.test.cjs \
  tests/team_view/knowledge-preparation-timeout.test.cjs \
  tests/team_view/knowledge-gap.test.cjs
```

The related knowledge-gap suite initially failed 33 cases because its old harness
only stripped the obsolete `setInterval(refresh, 5000)` footer. The current footer
also schedules recovery preparation refresh. The harness now checks and strips
only the exact known initialization string; it does not remove arbitrary timers.
Its 34 cases passed. The activity assertion now allows a live claimed role without
claiming a main invocation that has no fine receipt.

Existing read-model regressions passed **5 tests, 44 deselected in 0.39 seconds**:

```sh
.venv/bin/python -m pytest tests/team_view/test_live.py -q \
  -k 'valid_current_role_lease_presents_wait_instead_of_continue or current_queue_wait_overrides_stale_parent_and_active_delivery'
```

The exact live-lease cases now check ROLE_WORK_CLAIMED reason and a safe wait
instruction, replacing their prior assumption that a live lease proves a main
model call. The current wait override cases retain their original checks.

The three real Task read projections remain wired correctly: **1 passed,
10 deselected in 13.75 seconds**:

```sh
.venv/bin/python -m pytest tests/team_view/test_baseline_snapshot.py -q \
  -k test_task_read_snapshot_wires_all_three_real_projections
```

The pure baseline extraction previously passed the targeted history regression:
**4 passed, 10 deselected in 59.87 seconds**:

```sh
.venv/bin/python -m pytest tests/work_queue/test_baseline_history.py -q \
  -k 'qa_review_and_feedback or newer_epoch'
```

After final Schema regeneration with the existing generator's sorted TeamSnapshot
format, `tests/team_view/test_snapshot_schema.py` passed **17 tests in 0.73 seconds**.
The published diff contains the optional phase and the parent's new knowledge
failure classification; unrelated field order is preserved.

Ruff and strict mypy passed the 11 changed Python production/test files:

```sh
.venv/bin/ruff check \
  src/ai_software_engineer/team_view/knowledge_preparation.py \
  src/ai_software_engineer/team_view/queue_reader.py \
  src/ai_software_engineer/team_view/models.py \
  src/ai_software_engineer/team_view/reader.py \
  src/ai_software_engineer/work_queue/baseline.py \
  tests/team_view/test_knowledge_preparation_phase.py \
  tests/team_view/test_knowledge_phase_source.py \
  tests/team_view/test_knowledge_phase_queue.py \
  tests/team_view/test_product_execution.py \
  tests/team_view/test_snapshot_schema.py \
  tests/team_view/test_live.py
MYPYPATH=src .venv/bin/mypy <the same 11 files>
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

No full test suite was run. No MySQL tests were run concurrently with the parent's
queue worker. No production operation, delivery approval, SQL mutation or service
restart was performed by this task.

## 存量数据处置

无需改库或补造旧记录。新字段在 None 时从嵌套序列化中省略，旧 snapshot 和嵌套事实摘要保持
原语义。旧调用缺少可信细分记录时，页面显示已领取工作及等待说明。现存执行若已有精确匹配的
知识或主调用记录，下一次新鲜只读快照即可展示；不要求重建需求或改变原执行。父任务负责部署
和真实需求推进，本任务不批准或继续原需求。

## Limits and rollback

Knowledge intent reads are bounded to 512 filenames per supported lane; baseline
history is bounded to 100 records. Unsupported inherited baseline epochs do not
guess a fine phase. Phase is presentation only and does not certify completion,
verdict or model liveness beyond the separately validated current lease.

Rollback the optional projection/presentation and its Schema field together,
retaining the immutable invocation facts, queue history and all preserved work.
The production write algorithm retains its original authority checks. Independent
review by the parent remains required before commit.

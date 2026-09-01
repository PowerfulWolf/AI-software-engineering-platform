# T009 Verification

## Acceptance evidence

- `tests/orchestration/test_runner.py` 通过公开 `SerialOrchestrator.run_task` seam，使用真实
  `SqliteTaskRepository`、`FileArtifactStore`、`FileRunContextBuilder` 和 FakeAgentAdapter；
  fixture Task 走完 `NEW → PLANNING → IMPLEMENTING → QA → REVIEW → DONE`。
- 成功交付产生 5 个有序 StateEvent（repository revision=5）和四个 sealed Artifact；父链为
  `plan → implementation-report → qa-report → review-report`，数据库关闭重开后仍可读 DONE。
- 每个 role 都获得独立 run/context identity；QA/Reviewer 使用同一 candidate SHA；下游
  Context 只读取 ArtifactStore 读回的显式上游 Artifact。
- 反例覆盖 Agent timeout、QA FAIL、plan criterion 缺失、重复 run ID、非 NEW Task，并断言
  typed error、durable checkpoint 和未产生的下游 Artifact。
- Coder revision contract 已修正：request/context 是输入 base，implementation-report
  `source_revision == content.commit_sha`；QA/Reviewer 仍严格回显其 candidate。

## Quality gates

| Check | Result |
|---|---|
| `uv run pytest`（等价锁定 venv，`PYTHONPATH=src`） | 181 passed |
| `uv run ruff format --check .` | passed |
| `uv run ruff check .` | passed |
| `uv run mypy src tests` | passed; 57 files |
| `uv lock --check` | passed |
| `uv build` | source distribution and wheel built |
| `git diff --check` | passed |

## Known boundary

T009 是单 attempt happy path。QA FAIL、Review REJECT、Agent transient failure 的分类重试、
attempt 上限、BLOCKED 路由和进程中断恢复留给 T010；T009 会保留已提交 checkpoint 并 fail closed，
不自动猜测下一步。

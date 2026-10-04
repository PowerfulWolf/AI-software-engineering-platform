# 验证记录

## 通过

- `.venv/bin/python -m pytest -q tests/git/test_semantic_branches.py`：29 passed。
- `.venv/bin/python -m pytest -q tests/git/test_semantic_branches.py tests/recovery/test_resume.py -k 'successor or remediation or review_fixes or branch_name'`：3 passed，43 deselected。
- `.venv/bin/ruff check src/ai_software_engineer/domain/branch.py tests/git/test_semantic_branches.py`：通过。
- `.venv/bin/ruff format --check src/ai_software_engineer/domain/branch.py tests/git/test_semantic_branches.py`：通过。
- `.venv/bin/python -m mypy src/ai_software_engineer/domain/branch.py`：通过。
- `git diff --check`：通过。

本轮增量回归补充：

- `tests/git/test_semantic_branches.py` 验证稳定 Product 根与已占用 `-2` 分支的 `-3` 选择，
  以及无名历史 Task 保持 `None`。
- `tests/recovery/test_restart_contracts.py` 验证 `WorktreeAlreadyExists` 在首个 Coder 之前、
  且没有任何 Agent 证据时可进入严格快照分类。
- `ruff` 与 `mypy` 对 5 个变更源文件及新增测试通过。

## 限制

未运行仓库全量测试。一次带 MySQL 的恢复集成选择测试在既有恢复 fixture 的候选验证计划未生成处失败，
失败路径与本次分支名纯函数变更无关；按用户要求未扩大为全量回归。

## 存量数据处置和回滚

已有长分支、Task、审批、候选和 Artifact 不重命名、不 rebase、不迁移。服务重启后只影响新建 successor。
回滚方式是回滚本次平台提交并在空闲时重启服务；已生成的短分支和历史记录继续保留。

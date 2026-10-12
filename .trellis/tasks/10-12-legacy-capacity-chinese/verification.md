# 增量验证与交付说明

根因：历史文本使用无前缀 `no automatic retry.`，Python 和浏览器 exact map 只有
`no model retry.` 与带 `BUDGET_EXHAUSTED:` 的变体，导致两个 helper 均原样输出英文。

修复只补此精确句子的中文映射，说明容量暂停、平台调整输入装配与保留完整开发进度的恢复方案。
不根据 `RETRY_BUDGET_EXHAUSTED` 推断容量，不根据旧文本推断原模型未调用或额度未消耗。

验证：

- 红测：`pytest tests/team_view/test_blocker_text.py -q -k legacy_capacity`，
  Python/Node 精确句子 2 failed，普通预算与用户引用 4 passed，0.23s。
- `PYTHONPATH=src .../.venv/bin/python -m pytest tests/team_view/test_blocker_text.py -q`：
  72 passed，2.46s，含真实 Node helper 一致性测试。
- `.../.venv/bin/ruff check src/ai_software_engineer/team_view/blocker_text.py tests/team_view/test_blocker_text.py`：通过。
- 相同文件 `ruff format --check`：通过。
- `MYPYPATH=src PYTHONPATH=src .../.venv/bin/mypy --strict src/ai_software_engineer/team_view/blocker_text.py tests/team_view/test_blocker_text.py`：通过。
- `node --check src/ai_software_engineer/team_view/app.js`、`git diff --check`：通过。
- 独立只读 review：`/root/summary_result_scope_compat` scoped PASS，独立重新运行该文件
  72 passed，2.30s；确认 exact mapping、普通预算反例、无状态与存量写入。

这里 `.../.venv` 是主 checkout
`/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv`。
本集成 worktree 使用主 checkout 的 editable venv，测试必须显式 `PYTHONPATH=src`，确保读取当前树。
未运行全量测试。

存量数据处置：无需改库、修改 journal 或重新创建需求。服务加载兼容读侧映射后，原
Request/Task blocker 重新展示中文；Task.failure_code、执行次数、审批与历史原文完整保留。
此提交不增加恢复权限，不替代原需求的精确恢复检查。没有重启线上服务或执行需求操作。

风险与回滚：未知或拼写不同的历史文本仍保留原文，避免错误归类。回滚本次 mapping/test/spec
提交并刷新页面即可；不得为回滚改动持久化记录。回滚基线 `9cccb5b`。

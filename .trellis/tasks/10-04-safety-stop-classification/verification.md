# 增量验证及存量处置

- 修复前回归：两种首次安全暂停均误报 RETRY_BUDGET_EXHAUSTED，dirty timeout 文案遗漏恢复动作；3 failed。
- 修复后：`.venv/bin/pytest tests/e2e/test_unified_project_entry.py tests/team_view/test_blocker_text.py -q`：31 passed。
- 四个改动 Python 文件 Ruff check / format check 通过；两个生产文件 mypy 通过；git diff --check 通过。
- 未跑全量测试；未改 Schema/数据库/状态机、权限或 verdict。原始安全分类继续 fail closed。
- K1 存量 task_recovery_a02b14f64f91e492bf18de7cc6d9d4f6 的旧 checkpoint 不改写；保留 6 文件改动。重载后 projection 解释原始 timeout reason；基线更新后生成新 exact 恢复计划再批准。
- 浏览器控制工具不可用，实际页面验收尚未完成；中文 projection 由 Console API 和增量回归检查。
- 回滚：revert 本次平台提交，在没有活动角色时重启。不要删除 sidecar、审批或工作区。

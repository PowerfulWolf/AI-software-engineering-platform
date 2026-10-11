# 增量验证

2026-10-12：base 770c02e，独立维护 worktree；未修改生产运行仓、数据库或 Coder 草稿。

- 新真实 JS 控件红测：6 failed / 1 passed，证明 INVALID_OUTPUT 无入口及旧版本错误保留 SOURCE 控件。
- Python/JS 中文契约红测：11 failed，证明所有固定切片原因及旧 GIT 原因被吞成笼统失败。
- 最终相关 `node --test --test-reporter=dot tests/team_view/engineering-wait.test.cjs`：111 passed，含版本撤回、exact proof/cause、foreign Project、SOURCE/native-rule guards、copied report、known vs unknown cause 和原所有 wait regressions。追加运行不累加计数。
- `PYTHONPATH=src .../.venv/bin/python -m pytest -q tests/team_view/test_blocker_text.py`：46 passed；包含实际 shipped JS 与 Python parity。
- 两 Python 文件 Ruff check、format；blocker_text strict Mypy；JS syntax 和 diff check通过。

独立审查中发现已知新 WORK_SLICE 原因不能被当前方案再次显示成“具体旧校验子因未保存”，已用固定 native diagnostic 映射修复，并新增 plan/copied report回归。还发现旧停事实覆盖当前完整草稿结论，实际harness红测后加当前plan门转绿。

独立 reviewer 对最终 UI差异无阻塞发现；自行运行engineering+stopped-provider去重122 Node、blocker Python46、Ruff/strictMypy/JS syntax/diffcheck均通过。旧scope兼容修复和backend公共流程另行审查与集成；本任务不唯一裁决自己的实现。

后续 reviewer补充P2：旧generic wait分类下，真实SOURCE proof为INVALID，旧服务显示可点但提交必败。2版本实际DOM红测复现后，以分类或sealedproof错误双重版本门转绿。此修复不改变写门，display与callback一致。

存量数据处置：无需迁移/改库，所有历史失败、计数和审批保持。加载兼容后刷新原 K1，公开 prepare → exact engineering PAUSE → independent RESUME。部署和真实 K1 恢复仍待集成，本文不代表其候选或 QA/Review 已通过。

风险：未做浏览器视觉验收；DOM 单测不能证明线上性能。后端公共真实 native/SQL 闭环另由 backend task记录，不能拿本 UI 结果替代。

回滚：受控关闭后更新兼容版本，保留所有 immutable records；新 reason被消费后优先 forward fix，不得删历史迁就旧 reader。

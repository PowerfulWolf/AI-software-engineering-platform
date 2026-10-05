# 增量验证与独立复核

独立 checker 对最终代码与规范复核通过，无剩余 findings。

```sh
node --test tests/team_view/product-execution.test.cjs tests/team_view/delivery-status.test.cjs tests/team_view/knowledge-gap.test.cjs tests/team_view/engineering-wait.test.cjs tests/team_view/ui.test.cjs
# 82/82 通过
NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules node --test tests/team_view/browser/product-execution.test.cjs
# 真实 Chrome 6/6 通过，无 pageerror
.venv/bin/python -m pytest tests/web_console/test_manager.py::test_continue_rejects_a_stale_browser_without_resuming tests/web_console/test_manager.py::test_continue_hides_the_plan_reference_inside_manager_command tests/manager/test_stage_retry_budget.py -q
# 11 passed
.venv/bin/python -m pytest tests/web_console/test_core.py::test_file_store_reopens_hash_chain_and_interrupts_orphan tests/agents/test_structured_execution.py -q
# 4 passed
node --check src/ai_software_engineer/team_view/app.js
git diff --check
# 通过
```

仅运行相关增量测试。前端 JavaScript 没有独立类型编译步骤；Python 生产代码、API/Schema 与数据库契约未修改。
Chrome 同时验证中断红色、Designer 队列、exact checkpoint 接续提交、未知 native 拒绝普通继续，以及跨角色轮询不会把 QA 的执行事实复制给历史 Coder 或未来 Reviewer。

存量处置：无需改库；原 Operation 中断历史、Product 审批、Requirement checkpoint、预算与岗位身份保持。原 K1 已在只读核验旧 Host 与精确需求工作进程退出后通过公共 CONTINUE 恢复。更新静态资产并刷新即可加载修复，不重启活动 Designer。

已知限制：上游 Host 中断不是模型子进程停止证明，本补丁不实现 owned-run/progress/drain。回滚本次前端提交并刷新，所有原持久化事实保留。

最后窄修同时覆盖保留旧 Coder RUNNING step 且当前 QA RUNNING 的 payload：非当前 Coder assignment 不能继承 QA 的蓝色执行 badge。独立 checker 重跑 product-execution 17/17、Chrome 6/6、语法与 diff 检查通过；实现者最终相关轻量套件 82/82 通过。

部署后的生产只读 Chrome 核验于 2026-10-05T12:59:48Z/13:00:50Z 通过：K1 产品绿色已完成、设计蓝色执行中，Designer 成员及进行中队列一致。零 API 写请求、零页面错误；原始工程 UNKNOWN 保留。审计 JSON/截图存于仓库外的 maintenance/k1-delivery-20261005，未重启服务。

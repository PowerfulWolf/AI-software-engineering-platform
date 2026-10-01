# 实施与验证

仅跑本任务相关 Python/Node 增量测试；MySQL 用隔离 ASE_TEST_MYSQL_DSN 串行。生产 API 与浏览器复核，无全量测试。

## 2026-10-01 验证

- `pytest -q tests/recovery/test_knowledge_wait.py`: 15 passed；独立 QA 复跑 15 passed / 0.64s。
- `pytest -q tests/team_view/test_live.py -k 'current_queue_wait_overrides or active_child_task'`: 4 passed。
- `node --test tests/team_view/delivery-status.test.cjs tests/team_view/ui.test.cjs`: 15 passed。
- 原生 Git/MySQL joint scope recovery `[True-coder]`: 1 passed / 190.04s。真实 progress 接纳后知识等待、native attachment 前进程中断、fresh Host 接回同 Task、批准解答后新 claim Coder → QA → Reviewer → parent DONE。
- 同 fixture `[True-qa]`: 1 passed / 210.07s，原 verifier 等待路径回归通过。
- 四个修改生产模块 Mypy、七文件 Ruff/format、git diff --check 通过。
- 未跑全量测试。MySQL 测试使用隔离 ASE_TEST_MYSQL_DSN 串行运行。
- 独立 Reviewer 提出的 gap/manifest 错键、queue row identity/status 校验均已补齐并覆盖反例。
- 生产只读预检准确返回现有 gap `f3a2673bc6e0e2f0c2e895fc9247c8120ac67c45edaa5d5dfb3c036c543bef01`，原批准 recovery facts 校验通过，未修改数据库或运行角色。

## 生产激活与存量处置

- 无活动 Operation 时正常重启，服务 PID 50748（caffeinate，Console 8765）。前轮 requested-recovery-scope 同时加载，仍仅 terminal pre-candidate 有效。
- 原生 Continue Operation `operation_7cee275c191a3772163c05463052b950` SUCCEEDED，parent checkpoint `17695dcbf067d4f66ea17da3f2e5990a18f640e2901a4835ae659e4af4f9c782` 进入 WAITING_HUMAN，原 gap is_current=true。原 Task/attempt/progress/worktree/审批/预算保留，无手工 SQL 修复。
- 真 Chrome 页面验证：进行中0、阻塞中1；Manager 等待知识确认；实现步骤 class=blocked、显示已阻塞；仓库任务 badge 等待人工，文字明确保留实现检查点。截图 /tmp/ase-k1-knowledge-wait-ui.png、/tmp/ase-k1-blocked-task-ui.png。
- 用户补充发现 Continue Operation 仍可能遮挡wait：已补前端优先级与流程步骤修复；Node增加此回归，最终16 passed，独立QA复跑16 passed。
- 用户授权由代理合理回答缺失知识；正式批准 resolution `99f124131c5036ee6b88875c4274d9a76a170607f3591a66bdeb37df3313da75`，清楚声明知识解答不改变冻结权限、不宣称隔离MySQL能力已就绪、不把未执行测试记PASS。
- 后续原生 Continue Operation `operation_51c3c831bd4e4bf3e6b0582d7004efad` 已提交；这不是K1需求完成声明。范围/环境前提及最终候选QA/Review仍由后续流程完成。
- 回滚仅回退本任务代码；保留新journal/gap/resolution与HumanActionEvent，不重放旧审批，不删worktree。
# 知识答复后的存量推进

2026-10-01：通过正式 knowledge-resolutions API批准resolution
`99f124131c5036ee6b88875c4274d9a76a170607f3591a66bdeb37df3313da75`，明确旧fixture必须补真实接纳事实、文件权限需另行正式批准、隔离MySQL能力未就绪、不运行全量测试、不把跳过计为PASS。Continue operation
`operation_51c3c831bd4e4bf3e6b0582d7004efad` 已恢复同Task并写入原生HumanAction审计。

09:42:53Z第四轮progress `art_coder_c46f110237cb6e02d3c96c3bba783113` 被原生状态机接纳，SHA
`870c147d69ed6c9174c465261ec50df33bb9484bf2e95d01e524dfba7a419a13`；随后同Task自动进入第5轮并具有有效心跳。报告包含新的发布中断恢复、跨Project来源拒绝和采集条数上限修正，明确MySQL NOT_RUN和未批准文件范围。该报告仍是非候选checkpoint，不是QA/Review结论。

未改生产数据库、旧Task、原批准、预算或历史artifact；原worktree保留。当前旧知识gap显示is_current=false，与正常运行队列一致。Python/MySQL验证新模块仍未接入生产，不能把开发fixture结果作为本需求验收。

17:54本机Chrome实测：进行中1/阻塞中0；K1实现中；Manager协调处理中（继续交付）；与第5轮RUNNING、有有效心跳一致。截图/tmp/ase-k1-after-approved-knowledge-running.png。

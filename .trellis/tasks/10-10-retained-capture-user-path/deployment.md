# 原 K1 存量恢复验证（2026-10-10）

## 已部署与已验证

已提交并推送的源码为 `b4b3e13de038eca4250cc1a7e1139610468965dd`。
通过 `scripts/ase-console-service.sh restart` 完成受控收尾和新实例启动，Console
`delivery_ready=true`、operation contract 4。实际 HTTP 提供的 app.js/style.css 字节摘要
与本 checkout 相同。浏览器控制因认证不可用，尚未完成真实截图、键盘和视觉验收。

原需求 `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`、Task
`task_dc5cf0aee44e5ffe0cb600557204e0d0` 保持原身份。原 branch
`ai/feature/k1-auto-knowledge-20261005` 和 `coder-attempt-01` 工作区保持不变。

1. 公开 `PROPOSE_EXECUTION_BASELINE` operation
   `operation_81b12dc1b2781fb21cd0ac099ca70ef3` 成功；plan
   `9843e812a44fc7cb1f0ebb78449a19c768deec3f5926d620887278af89ad9702`。
   原 Run `run_ace680664bb14ad8abadc70f967d9d2a` 的真实停止经验证，缺失 receipt
   通过合法封存补齐。完整草稿为 27 文件、342336 patch bytes，未先调用 HANDLE。
2. 已通过公开 native-rules GET 逐项审阅 8 项精确项目规范变更，批准 change digest
   `b3dfb0a28dd335769295fabac60790f12fba2379247e4d2f04525e1848a4b09c`。
3. 公开 `EXECUTE_EXECUTION_BASELINE` operation
   `operation_16d2c2b7d55cd29ed0ccb1169d07a604` 成功，明确 `continuation_mode=pause`。
   绑定 `492bb61b109082225daf5df658c0d8027860421d4072cda6dd03a0145dcc51ef`；当前
   execution base/source 为 b4b3e13，旧 Task.base_ref 和历史保持原值。
4. 实际 Git 只读检查：同一分支 HEAD 为 b4b3e13，27 文件草稿仍在。公开 Team
   读取确认 Task 仍为 IMPLEMENTING/revision 17；旧 WorkItem 已关闭，新预留 Coder
   attempt 8 为 WAITING_HUMAN/EXECUTION_BASELINE_PAUSED。此次维护未启动新模型。

没有直接 SQL 重写、删除审计历史、重新创建需求或绕过独立 QA/Review。
此前一处测试样例的外部维护及 HumanActionEvent 保持原记录，本案例不能归因完全自治。
这证明原存量可以安全保存并更新基线，**尚不证明原 K1 已通过 QA/Review 或已交付**。

## 实机新增发现与后续

提案耗时 264.509 秒，执行 PAUSE 约 244 秒。只读性能测量发现 baseline service/store
没有共享既有有界 source_inspection_scope；同一 plan+receipt 重读从 4.282 秒降到
0.206 秒，digest 相同，但该测量不能单独解释整个操作耗时。独立 Trellis 任务
`10-10-baseline-source-inspection` 继续修复和测量，不修改原封存事实。

基线完成后曾收到 Team 503，后续读取恢复 200，未从那次响应确定是忙碌还是不可用。
前端真实 harness 则复现：Team 读取失败、Console/Operations 成功时，旧 snapshot
仍能提交操作。独立 `10-10-stale-team-control` 负责保留阅读并暂停旧事实上的操作。

完成上述运行时/交互修复后，从最新 Team 快照提交精确 RESUME，再由原 Coder、独立
QA 和 Reviewer 推进原需求。不能把平台增量测试或 fake adapter 闭环当作实际 K1 验收。

## 回滚

原 receipt、binding、PAUSE 与规范 epoch 已发布，必须保留兼容 readers。优先向前修复；
回滚运行时代码不会撤销已批准的 source 更新。再次改 source 必须追加精确工程方案，
不能 reset/rebase 原工作区、改写 Task.base_ref 或删除事实使旧代码读取成功。

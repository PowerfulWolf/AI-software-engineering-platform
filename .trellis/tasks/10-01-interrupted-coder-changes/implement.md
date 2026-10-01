# 实施与验证

基线 `be35741`。中断恢复原入口同时在提案与 `_execute → seed.seed` 阶段要求原 seed
完全不变，合法的运行中新增改动因此触发 WorktreeCaptureRejected。改为独立封存完整
stopped_capture，逐次重验精确审批；replacement 打开保留工作区但不重播原 seed。
保持原 Task、预算、权限、seed/invocation 历史以及独立 Coder/QA/Reviewer。

## 增量验证

- 原实现 `test_exact_interruption_resume_keeps_seed_and_old_invocation[True]`：
  RED，1 failed / 84.15s，复现提案错误拒绝。
- 第一版恢复执行仍调用 seed.seed：1 failed, 1 passed / 325.87s。独立 Reviewer 指出
  同一实际入口遗漏；改用 prepare_workspace 后关闭 finding。
- `.venv/bin/pytest -q tests/recovery/test_interruption_native.py --tb=short`：
  2 passed / 322.13s。隔离 Git/MySQL、offline adapters，分别覆盖未变 seed 和合法新增
  改动，新 claim/Run 后 Coder→QA→Reviewer→DONE；保留旧 seed/invocation。
- 独立 QA 快测：capture、records、Console interruption，18 passed / 11.16s。
  覆盖 staged/unstaged/new file、proposal 后内容/index/HEAD/身份漂移、越权、危险文件、
  旧 wire/digest 和审批事实展示。
- 9 个变更 Python 文件 Ruff check/format、Mypy 全通过；git diff --check 通过。
- 独立 Reviewer 最新复核无新问题，原 high finding 已关闭。

未运行全量、未把业务 DSN 用于测试、未直接修改生产数据。上述离线结果不是 K1 的最终验收。
浏览器认证工具暂不可用；本轮展示验证限于实际 Console 逻辑的回归与生产 HTTP 投影。

## 存量数据处置

无需改库。现有 K1 Task `task_recovery_e35017a761b1037b5a1318e151250922` 保留
ed12f25 基线及 20 个 dirty 文件；旧 lease 已过期，旧 Operation 的失败和中断记录保留。
所有 Operation 停止后受管重启加载修复；普通 Continue 生成当前完整改动的计划，核对
身份/文件/摘要后按用户授权批准 exact plan，再由普通 Worker 重新领取并推进独立验证。
待真实激活后追加 plan/Operation/claim 结果，不预先标记业务交付完成。

## 风险与回滚

新字段兼容旧记录，但旧版本不能消费含 stopped_capture 的新计划。回滚代码时保留所有
记录与 dirty worktree，停止新的恢复执行，不删除审批或重置任务。只允许一次 replacement；
再次未知中断仍拒绝自动重放。回滚点为 be35741。

## 真实激活与恢复（2026-10-01）

- `9f00cf7` 已推送 origin/main。确认所有 Operation 停止、旧角色 lease 已失效后，通过
  受管脚本 restart 加载；新服务 PID 51553，`GET /api/v1/console` delivery_ready=true。
- Continue `operation_1c574cfd634cb4446adce510002e9993` 成功生成 exact plan
  `5e3370af1489b5d7f2003c10fed053e6ae53cb99c65efdbb839201994e3462a2`；当前快照
  `e566dd85e1a780d5bb7588df8775639c58df1ae0a0e6e244096daed02d15ea9d`，20 文件与
  原工作区、分支和 ed12f2550093ed3247775276eacf89339b68efb5 HEAD 完全对应。
- 按用户授权经正常 POST 审批，Operation `operation_bcdbe757d0b507896544852e8efc0634`。
  新 invocation 于 13:51:23Z 封存：dispatch_sequence=1，lease_275e2a5c80dbec1fba72f08a，
  run_c1904be3d59e4e448bb924b3b32bfff6；旧 invocation SHA 仍作为 previous 引用保留。
- 14:05Z 实际 Coder 子进程在运行，heartbeat=14:05:01Z、lease 有效；读取工作区证明
  learning_collection.py 及两个测试文件已相对批准快照继续修改。
- 当前请求仍 DELIVERING、Task IMPLEMENTING，旧中断 blocker 已随新租约消失；
  `node --test tests/team_view/delivery-status.test.cjs` 10 passed / 62ms，涵盖旧 Manager
  审批不遮当前执行、失租约中断、审批消耗和新 claim 状态收敛。
- 浏览器认证仍不可用，未宣称 Chrome 实测成功。当前修复完成；K1 尚无本轮 candidate、
  QA/Review verdict，业务完成状态继续跟踪，不能由这些平台回归结果替代。

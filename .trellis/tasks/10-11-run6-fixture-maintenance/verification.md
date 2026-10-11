# 验证与交接

2026-10-11，本子任务尚未执行 production apply。

- 只读 prepare 通过，生产写入 false，exact plan digest：
  `4045db7748a5b6d7429c0124a0d71d4a17898f2f0bd967afe9b7e61fb5049174`。
- 唯一目标文件 before：`737b0d716c72823f9eace6a4fb683a8c8005e2bd7adb815fc1ab244cc1c8ba52`。
- 唯一目标文件 after：`6eecedca03233034c6946e007d2cc255105a88a7ab2263266112777dc0d7c4e9`。
- 隔离完整 28 项变更：原 capture 为 `WorktreeCaptureRejected`；仅修改目标文件后，
  完整 body/patch capture、typed wire roundtrip 与 verify 全通过。
- 原 HEAD/branch/index 保持，完整副本 inventory 仅目标文件变化，测试后也保持不变。
- 精确未知/空/过期 fence 负向 node：1 passed；完整 `test_bounds_retry.py`：19 passed，
  无跳过，包含使用副本源码的真实子进程并发测试。
- 两脚本 scoped Ruff 与 strict mypy 通过；原生产事实在隔离验证前后与冻结计划相同。

机器可读证明见 `verification.json`，没有保存完整草稿、模型输出或私密推理。
未声称整个 K1 通过 QA/Review，本验证只证明这次外部 fixture 改写的必要边界。

待 Root 独立审查后，维护停服、集成、由 Root 执行 exact apply、提交完成证据与推送，
再启动最新服务并通过公共 baseline proposal/execute-pause/resume 路径继续原需求。
本子任务不运行真实交付、不产生 QA/Review verdict，也不直接接纳原执行。

## 生产维护结果

Root 在 2026-10-11 10:52:02 UTC 完成精确 apply。旧服务 PID 52944 已通过
`console_shutdown_15eed66874006e3041734eb8add6da4b` 的 exact READY 后真实退出。
仅目标测试文件改变，完整 capture/wire/verify 通过；Task/work6/revision/HEAD/branch/index
及预算保持。生产审计在受控 sidecar `state/external-test-maintenance/<plan_sha256>/`，
包含授权、完整前后正文和补丁；仓库仅保存脱敏展示、哈希计划与 completion。

`evalevt_external_tests_4045db7748a5b6d7429c0124a0d71d4a` 记录人工 MODIFY_TESTS，
不能归为 ASE 自治产出。本维护没有补造 receipt/outcome、通过 QA/Review 或继续模型调用；
后续由公开 baseline proposal/execute-pause/resume 完成真实封存、源码更新和交付。

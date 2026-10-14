# K1 前提门修复与最新 main 存量恢复

目标：修复 Coder 被验证角色前提等待提前阻塞的问题；保留 K1 原批准和历史，使用最新 main 通过公开基线流程继续交付。

范围与允许路径：manager/{delivery_preflight,preflight_gate,delivery_wait,native_verification,python_verification,python_verification_runner,delivery}.py；multi_directory/{planning,service}.py；recovery/verification_entry.py；web_console/models.py；对应 tests/；三个嵌入 selection Schema；fault-retirement Schema ID 及其生成器；.trellis/spec/core/delivery-preflight.md。

验收：旧精确 pytest 兼容但越权/无注册能力仍拒绝；64 节点真实 runner 输出有界，65 拒绝；已有 planned 文件不要求新增写权；Coder 继续不跳 QA/Review；Planner 可行动反馈与原预算修正；公开 baseline 精确绑定最新 main 且保留旧事实；生产尝试具有新的真实 claim/Run。

验证：ruff、mypy；tests/manager 的 preflight/native verification/wait/runner/Planner/baseline 回归；tests/planning/test_verification_feasibility.py；公开 Schema 契约。需要 ps 的真实进程测试在受控 sandbox 外执行，不改变进程归属安全。

回滚点：平台 main a81ace0f4f938dfd2c9db13bb65f6585c3b939db。回滚实现后受控重启，不删除原审批、候选、claim、baseline 或等待历史。业务交付只交 candidate/evidence，不自动合并或部署。

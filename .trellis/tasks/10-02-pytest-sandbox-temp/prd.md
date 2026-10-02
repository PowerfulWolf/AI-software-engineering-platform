# 受控 pytest setup PermissionError

## 目标与范围

K1 新精确验证计划 9179235e 的 32 个节点展开为 43 个用例，全部在 setup 阶段
PermissionError(1)。用真实 OS 沙箱最小 fixture 定位公共初始化问题，修复可信执行器，
保留源码只读、独立 scratch、Task deny 与无网络边界，不改 K1 业务 worktree/verdict。

## 验收

- 最小真实沙箱回归先红后绿，tmp_path/临时目录与现有负向权限同时成立。
- 只跑相关增量 runner、权限与执行契约测试，不跑全量。
- 修复激活后必须重新提案并批准；旧 receipt/审批/Task 均不可覆盖或重放。
- 独立 QA/Review 检查平台修复后再提交推送、空闲激活、继续原生 K1 交付。

## 允许路径 / 验证 / 回滚

允许可信 Python runner、其相关 tests/manager 测试、verification-environment spec 与本任务。
验证真实 macOS sandbox test、runner tests、Ruff/Mypy 和 diff check。
回滚修复提交并在无执行时重启；保留全部生产事实，重新获得精确验证授权。

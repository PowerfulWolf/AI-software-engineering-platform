# 桌面维护工具沙箱归属误阻塞

## 目标与现场

用户在原 K1 点击准备恢复仍遇到 LEGACY_LOCAL_EXECUTION_ACTIVE。最新操作
operation_1cb5e819019fd002cc58a873fc766df3 的实时只读复核发现全账户仅有
CODEX_WRAPPER_ACTIVE，原工作区无 cwd/open-file 占用。两个 native codex sandbox
属于 ChatGPT CUA REPL 的 kernel/trusted-worker 工具，不属于旧 Coder。
之前只排除直接控制入口，未识别控制入口的真实工具封装，因此正常维护也阻塞恢复。

## 范围与验收

- 用 OS executable path、native name、PPID、birth、准确动作/脚本及两次一致清单识别
  ChatGPT bundle 的 sandbox → node_repl → node(cua-repl.mjs) → codex(app-server) → ChatGPT。
- 仅上述可核验工具 sandbox 不产生全账户 wrapper 阻塞。不是对任意 sandbox、临时脚本名
  或维护进程树的豁免。
- 原工作区 cwd、所有打开文件和派生工具仍完整检查；真实 exec/e、未知/orphan wrapper
  或身份/链漂移仍阻塞；缺 fresh coverage、权限、超时/截断仍调查不完整。
- 旧 Run UNKNOWN、草稿、HEAD/index/branch、审批、人类实际停止声明、队列与 Schema 不变。
- 真实 K1 只读调查不再因已核实 CUA 沙箱误报，并验证工作区完整性前后不变。
- 公开 Host 恢复测试通过，保留同 Task、旧历史和独立 QA/Review；不操作生产恢复。

## 验证与回滚

仅扫描器、legacy rescue/containment、相关 Console/Schema 的增量测试，Ruff/format/严格 mypy。
完成后提交推送。回滚本次提交恢复更保守的误阻塞，旧存量无需迁移；不清空工作区或改库。

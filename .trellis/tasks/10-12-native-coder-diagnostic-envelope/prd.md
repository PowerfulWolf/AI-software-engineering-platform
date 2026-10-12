# 真实 Coder 执行包装的中文诊断

## 目标与证据

上线后 K1 的真实 INVALID_OUTPUT 文本包含 `coder run run_cd17fc4c9d254fdf8ae13f19d0cc1fe9 failed: `。
现有 Python/JS 只匹配内层固定 native 前缀，导致已知 GIT_CONTRACT 降成笼统执行失败。
新增真实包装 parity 用例已在修复前得到 11 failed / 46 deselected。

## 范围、契约和验收

- 只在 `_coder_output_diagnostic`/`coderOutputDiagnostic` 中去掉精确一层 anchored Coder/run 包装。
- 保持 native 固定前缀、分隔 machine token、未知原因和脱敏行为；不反射异常正文。
- direct/real envelope 的九种已知规则、未知规则、GIT 原因 Python/实际 shipped JS 一致。
- foreign/nested/malformed/free-text 包装不获得固定诊断；不猜原 K1 的具体历史子因。
- 不改状态、Schema、审批、旧事实、工作区或队列。

## 允许路径

`src/ai_software_engineer/team_view/{app.js,blocker_text.py}`、
`tests/team_view/test_blocker_text.py`、`.trellis/spec/core/unaccepted-coder-draft-ui.md`、本任务目录。

## 验证与回滚

只跑 blocker 文件、engineering-wait Node 增量、Ruff、strict mypy、JS syntax 与 diffcheck。
独立审查后 idle controlled stop/FF/start，上线读实际 K1 中文原因。
回滚该提交前受控停服；保留全部记录。无需 DDL/改库，现有需求刷新就获得正确展示。

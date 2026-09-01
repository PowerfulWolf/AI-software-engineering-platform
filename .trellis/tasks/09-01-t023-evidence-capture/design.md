# T023 Design

## 边界

```text
CommandExecutor / AgentAdapter / Git inspection
        ↓ typed result
RunEvidenceSession
        ↓ redact + bound + seal
FileEvidenceStore (evidence records + run manifest)
        ↓ Evidence references
Artifact / Evaluation / Handoff
```

Evidence 层只封存事实，不解释事实为 PASS/FAIL。`RunEvidenceSession` 由上层按每个独立
`run_id` 创建；它通过 `operation_id` 生成稳定 evidence ID，重放时要求 payload 完全一致。

## 数据流

1. `capture_command` 调用已有 `CommandExecutor`，不新增 subprocess 路径；异常也先写 rejected/
   timed-out/failed-to-start record 再重新抛出；
2. `record_diff` 和 `record_test` 只接受已由调用方获得的 typed facts，所有文本先脱敏和限长；
3. `record_agent_result` 只接受与 session identity 对齐的 `AgentResult`，保存 provider-neutral
   usage/error；
4. `seal` 扫描该 run 的完整 evidence，生成 immutable manifest；
5. `EvidenceCapturingAgentAdapter` 作为可选 decorator，在返回 AgentResult 前封存 usage evidence
   和 run manifest。

## 安全约束

- 复用 Context 的 redaction pattern，但实现放在共享 `redaction.py`，避免 evidence/context 两套
  脱敏规则漂移；
- store root 不得为 symlink，evidence 与 runs root 不得重叠；
- digest 不包含自身 digest 字段；读取时重新验证 Schema、filename identity、record digest 和
  manifest 引用完整性。

# 增量验证与存量处置

## 红测与实现

初始全七角色失败记录测试：7 failed / 0.39s，模型执行时没有调用前意图。
实现后真实 KnowledgeConsultationService 在每个知识 phase 保存意图和完整结果。
所有七角色使用同一机制；旧consultation/model-call/gap契约与摘要保持兼容。

## 验证结果

- `pytest -q tests/knowledge/test_invocation_receipts.py tests/knowledge/test_consultation.py tests/knowledge/test_schema_parity.py`：75 passed / 1.07s。
- `pytest -q tests/knowledge/test_invocation_receipts.py tests/knowledge/test_delivery_context.py tests/knowledge/test_joint_recheck.py tests/knowledge/test_schema_parity.py`：73 passed / 2.63s。
- `pytest -q tests/knowledge/test_invocation_native.py`：34 passed / 10.79s。
- `pytest -q tests/knowledge/test_store_read_limit.py tests/knowledge/test_schema_parity.py`：24 passed / 0.33s。
- 涉及生产文件和测试的 scoped strict mypy、Ruff、format、git diff --check 通过。
- 独立review先运行structured/journal/schema 85条增量；修复的owner-loss、NOT_STARTED边界
  再加入完整journal/service回归，避免仅依靠手动反例。

仅运行相关增量，未执行全量测试。native测试使用真实Python fixture进程，不连接真实模型。
覆盖真实进程限时/非零/invalid、跨进程重放、未完成拒绝新run/context/source、独立stop、
写失败不fallback、真实QueueClaim、owner-loss拒绝备用路由，以及missingexe完整NOT_STARTED闭环。
list限额在读取payload前拒绝超限，不将全量history解码后再计数。

## 存量数据处置

没有修改生产SQL、Task、Operation、审批或已有knowledge bytes。历史未知失败没有补造收据。
现有K1已通过公开精确恢复方案8ca继续，27文件现场保留；运行中的服务/Task不热加载本次改动。
部署必须等活动Operation完成或明确受控空闲后重启。后续调用产生新journal；本次修复没有
擅自更换活动Task基线，也不需要用户重建Requirement。

## 已知边界与回滚

收据不授权自动续跑，不改变local limit为provider transient，不产生QA/Review verdict。
知识local limit的同Task自动续跑仍需独立冻结预算/claim契约；不能用stop摘要伪装完整恢复。
回滚仅在空闲时恢复前版composition；保留所有新收据、原日志和现场，不能删除pending解锁。

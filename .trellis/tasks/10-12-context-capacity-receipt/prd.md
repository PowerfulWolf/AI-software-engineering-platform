# 上下文容量停止的可信执行前记录

目标：最终 provider payload 超过已冻结输入预算时，在 invocation start 之前封存真实 claim、Task、Context、source、baseline 与容量估计。容量不足属于平台工程前提，不能伪装工作额度耗尽、模型失败或旧调用结果。

范围：agents/model_input.py、manager/context_capacity.py、preflight_gate.py、production_backend.py、新 standalone Schema、相关增量测试。回滚点 7ef2425。只通过真实 Worker owner fence 发布记录；不改生产SQL、历史Task、verdict或授权。

验收：实际最终输入超限、零 invocation start/outcome/provider、receipt/hash完整、身份/已有start/store失败全部拒绝；legacy observation明确不包含缺失request/final count；已有native验证receipt保留。关联恢复路径必须重读完整receipt与当前事实，并单独精确审批。

验证命令：增量 pytest tests/manager/test_context_capacity_receipt.py tests/agents/test_model_input_preflight.py tests/manager/test_verifier_preparation.py；变更文件 Ruff、strict mypy、git diff --check。不跑全量。

# 实现与交付记录

## 根因 / 修复

恢复入口只重建原 Requirement 与 prerequisite 目标，遗漏失败 Coder manifest 中的 standalone
remediation.verification 与 native QA/Review artifact 输入。因此代码 seed 被保留而具体 finding 丢失。
新 helper 重验完整封存来源并作为 required ContextSource 路由；共享独立验证反馈序列化保持历史 digest。

## 验证

`.venv/bin/pytest -q tests/recovery/test_recovery_verdict_context.py
tests/recovery/test_remediation_context.py tests/recovery/test_prerequisite_repair.py
tests/recovery/test_reapply.py`：24 passed，1.33s。
Ruff check/format、strict Mypy（context.py/entry.py/remediation.py）、git diff --check 通过。
只读真实 K1 plan d4abeb12 回放：封存 finding_qa_legacy_corruption_unrecorded 完整保留；
已接纳 ctx_50636... 字节不变，零模型调用、零生产写操作。
独立 Review 与独立 QA 均无阻塞 finding；QA 另跑16项关联增量及跨3个新 Task 的
Review REJECT/脱敏/权限/完整性只读 fixture。其低优先级建议已落实：native 持久测试
参数化 QA/Review，并将 successor 改为新 Task；单文件8 passed，0.67s，Ruff再次通过。
这些工程检查不构成 K1 原生 verdict，未跑全量测试。

## 存量数据处置

无 SQL migration、无 Task/Context/审批修改。K1 新候选 e41ffbb7 本轮独立 QA FAIL：
损坏 legacy 来源缺失审计、损坏 Task/事件导致整页中止。自动回派 attempt2 在知识准备阶段
TIMEOUT，未启动 Coder 模型；现有候选/报告保留。此 candidate 后续通过新精确计划做受控
增量验收并正常回派，未来失败 Coder 的新 recovery 才消费修复后的 required 来源。

## 激活 / 风险 / 回滚

仅在无 RUNNING/REQUESTED Operation 与有效角色执行时重启。提交推送后，将注册仓库 main
fast-forward 到平台修复基线，不合并 K1 candidate，不改已批准执行的冻结基线。
完整反馈可能触发现有预算门；此时拒绝调用，不静默截断。回滚平台提交并空闲重启，保留持久事实。

# QA/Review 模型前容量等待继续

目标：同候选、同 Task/WorkItem、同 attempt，以新 dispatch/claim/Run 继续未调用的
QA/Review。保留原 READY native 准备、完整 Context、历史与计费事实；不退款、不生成 verdict。

允许路径：domain/delivery_resolution、manager/capacity_input_reader、baseline_production、
delivery_wait、work_queue/execution_store、preparation_resume，相关 Schema、生成脚本、增量
tests 和 delivery-preflight spec。Console 操作/按钮与平台总容量 spec 由 root 独立负责。

契约：VerifierPreparationEvidence.context_capacity_receipt_sha256 和
context_capacity_claim_sha256 同存同无，缺省不进入 wire/hash。容量 proof 只支持
RESUME_UNINVOKED；FINISHED 必须真实完整成功，budget_source/native_failure_code 为 None。
普通 FINISHED 准备仍使用 frozen_work_attempt 的原重试规则。

调查：精确 context-capacity://SHA → 完整 receipt/Context/Task/原 claim/历史 step/授权基线 →
唯一原 READY intent/checkpoint → 当前 native observation 不变 → 当前前提 READY →
完整 invocation/outcome/route/native/原始 Artifact 事实无本 claim 的模型调用或产出。
所有 matching 记录键、SHA、关联、目录/regular 文件与字节上限须校验；alternate Run/Context
不是不同 claim 的证明。当前 verifier 和历史 Coder markers 的 later-claim 条件不同。

继续：Worker lock + MySQL Task/queue fence 下重新核对精确 candidate/Task/claim；
同工作项只 dispatch++、真实新 claim，不加工作轮次、不退款。preparation_resume_consumed
核对两 CLAIMED 之间的真实 WAIT_RESOLVED 后准许新准备意图，原 READY/native 字节保持。

验收：公开 Coder 和 QA/Review 各一轮/两轮容量停止→精确决定→新 claim→独立交付到 DONE；
真实 FINISHED native 准备仍能继续；全部 same-claim alias、坏记录、混用 proof 均 fail closed。
旧 verifier preparation 与普通 frozen-budget Schema 用例通过。完整可执行契约和矩阵见
.trellis/spec/core/delivery-preflight.md 的“模型前输入容量等待的原候选继续”。

验证：仅本任务增量 pytest、Ruff、strict mypy、diff --check。公开测试使用隔离 MySQL；
不操作生产数据库、服务或需求。本任务增量内容无 SQL 数据迁移；发布后存量有完整 receipt 的
QA/Review 可在原工程调查→精确继续入口推进。无法补齐的历史等待仍 fail closed。

回滚点：ec55d53（QA/Review 本次实现提交前集成 HEAD）。回滚实现时保留新增 proof 的只读
Schema/域字段兼容和已保存历史，不能删除原审批或重置 Task。

# 联合设计在原生交付入口才被拒绝：复盘

## 1. 根因类别

跨层契约与覆盖缺口。联合层只检查外层结构、覆盖和 readiness，原生转换额外检查
verification inspection 是否承担了无法完成的 integration/security 义务。相同设计先
被接纳并交给 Planner，后来才被真实 native validator 拒绝；原具体原因又被通用
“Designer did not publish a verified planning handoff”覆盖。

## 2. 修复边界与失败分析

仅翻译通用提示不会修复流程。只在新设计接纳加校验会把现有 K1 留在不可继续的终态
parent；直接扩大 INVALID_OUTPUT 重试或接受旧设计则绕过安全契约。仅保留上一轮
feedback 会在多轮弱稿覆盖或知识等待后丢失原验证要求。只检查当前已派生 child 又会
漏掉其它已批准源码；公开入口先 reconcile 还可能重建本该用于证明的缺失基线。

## 3. 防复发机制

- publication 与 native conversion 复用同一 validator，Planner 只收到接纳通过的设计。
- 原拒稿、精确验收 ID、可执行验证要求通过可核验历史与 typed 模型输入传给 Designer。
- 同一 Product/approval/scope/source 的最低验证义务跨多轮、wait/recheck 保留；禁止以
  删映射、改 reference_only 或替换反馈规避。
- 公开 Console/Host 及 locked service 均避免在证明前重建事实；纯只读 proof 检查所有
  scope 基线、完整 parent/native 历史、真实失败 receipt、Product/approval/context SHA。
- 剩余预算、职责及最新 checkpoint 门禁保持；不修改旧 Task、verdict、预算或批准。
- exact fake composition、实际输入 Schema 和公开恢复负向测试纳入增量验证。

## 4. 系统扩展检查

检查了共享 PlanTestItem 的全部静态 `$defs`，确认多个 bundle 未同步现有验证字段，
另立 joint-verification-schema-sync 任务修复；不以删字段或放宽 additionalProperties
规避。旧 model parsing 未纳入 publication 新约束，保留历史可读和 bytes/hash。

## 5. 知识沉淀与生产限制

可执行恢复契约、Good/Base/Bad 与测试矩阵已写入 multi-directory-delivery code-spec；
静态嵌入传播要求写入 python-runtime code-spec 与 docs/architecture/contracts.md。
真实 K1 只读 proof 核验 4401 个 Project 文件前后相同；发布后仍须通过公开 exact
CONTINUE 追加新 Designer/Planner 产物，并走独立 Coder/QA/Review，不能把修平台测试
通过称为业务需求已交付。

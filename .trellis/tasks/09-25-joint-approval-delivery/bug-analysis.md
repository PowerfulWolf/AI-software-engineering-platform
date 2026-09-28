# Bug Analysis: 审批返回导致计划自行过期

## 1. Root Cause Category

B（跨层契约）+ D（测试缺口）：Host 把“同步子交付实际变化”错误扩展为“任何返回都追加父 journal”，而 native plan 严格绑定父 digest。

## 2. Why Fixes Failed

上一轮只验证 pending gate 没被 Host/UI 丢弃，测试甚至要求追加父 checkpoint。未验证用户点击该审批后是否真正执行。UI 可见不是交付成功。

## 3. Prevention Mechanisms

- P0：pending gate 无变化时父 checkpoint 稳定，三种 gate 单测覆盖。
- P0：真实 Git/MySQL 验证完整 propose/repeat/approve/independent-verification/parent-DONE 链路。
- P0：保留 exact parent drift 校验；在提案前同步真实变化，不在提案后使其失效。

## 4. Systematic Expansion

verification、recovery 和 scope 都经过同一 Host seam；覆盖全部三种。跨进程/旧父观察值也纳入回归。生产验收必须检查业务 checkpoint 与证据，不以 Operation SUCCEEDED 代替。

## 5. Knowledge Capture

已更新多目录交付规范；本仓库没有 `src/templates/markdown/spec/` 模板树，无需生成模板。旧生产计划和操作记录全部保留，经正常入口重提当前计划，不篡改其历史绑定。

## Bug Analysis: Responses 真实工具循环兼容性

### 1. Root Cause Category

B（跨层契约）+ E（隐式假设）：strict Schema 未覆盖全部工具可选字段，最终输出使用根 union / 任意对象；工具续接还假设兼容网关会保存 response ID。

### 2. Why Fixes Failed

只修审批使真实 QA 得以首次进入模型工具链，并非已经验证完成。首个 HTTP 400 没有透出原因；补齐安全诊断和 Schema 后，第二个错误才明确为 `Previous response not found`。两个缺陷必须分别验证，不能把 API 首轮成功等同于完整角色成功。

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Contract tests | 检查每个角色 outbound strict Schema、元数据 round-trip 和原有 verdict 拒绝行为 | DONE |
| P0 | Tool-loop regression | 模拟不保存 response ID 的网关，断言完整上下文、reasoning、call IDs 和 receipts | DONE |
| P0 | Safe diagnostics | 共用先脱敏后限长的错误提取，Console 保留 typed role failure | DONE |
| P0 | Live acceptance | 通过正常 exact-plan 审批跑真实 QA/Reviewer，不重放已消费 Run | IN PROGRESS |

### 4. Systematic Expansion

Structured-model 与 Delivery Responses 共用错误提取和 Schema normalizer；联合 Host 的真实交付门禁不降低。Swift/XCTest/UI 验证权限缺失属于另一条潜在阻塞，不能靠这次 wire 修复或改历史 Task 隐式扩权。

### 5. Knowledge Capture

已新增 `.trellis/spec/core/responses-wire.md` 的七节可执行契约并链接到 core index。尚未结项或提交，必须保留真实交付未完成的状态。

## Bug Analysis: Swift capability and stale unstarted plan

- Root cause B/D/E：语言检测不识别 Swift，历史计划封存 Git-only；current-policy 校验只重算旧
  definitions 自身 digest，未比较新候选能力。执行时的分配 guard 才发现差异，导致继续审批报错。
- Red loop：真实 Git/MySQL `test_joint_verification_approval_stays_current_and_completes_delivery[True]`
  在权限变更后旧批准抛 `current Agent/model allocation differs from approved plan`；同时 argv
  回归发现 `-c`/`--configuration` 别名重复未被拦截。修复前 2 failed / 27 passed。
- Fix：未启动计划比较当前候选权限并正常重提；已入场/封存历史保持有效；参数别名归一后查重。
  修复后基础/权限变更两条联合交付路径与命令测试 30 passed。
- Prevention：真实候选 tree 检测、旧批准零调用、新计划 digest 改变、Coder 权限不变、原 Task/events
  不变、context plan/candidate/command 一致、UI 精确命令事实以及 JSON Schema parity 都纳入测试。
- Knowledge：`.trellis/spec/core/swift-verification.md`。Swift/XCTest 工具链可用性与 UI 账号/样本是
  独立前提，不能靠主分支构建成功、静态检查或重复审批伪造候选交付成功。

## Bug Analysis: Safe but unlocatable CLI validation failures (2026-09-26)

### 1. Root Cause Category

B (cross-layer contract) + D (test gap): CLI intentionally excluded raw Pydantic
messages for privacy, but collapsed different semantic validation errors to
`value_error; path=qa-report`. An output hash identifies bytes but cannot explain
which rule failed after the transient output is removed.

### 2. Why Fixes Failed

Earlier tests asserted only that a generic cause and root were present and private
text was absent. They did not require missing evidence, inconsistent verdict and
wrong producer to be distinguishable. The live rejected report cannot be recovered
from its hash; its exact cause remains unknown, not automatically "missing evidence".

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Red-to-green adapter regression | Require fixed UNKNOWN_EVIDENCE_REFERENCE diagnostic while still rejecting the report | DONE |
| P0 | Privacy contract | Emit only fixed rule constants, never messages, inputs, IDs or arbitrary location keys | DONE |
| P0 | Negative coverage | Inconsistent verdict, producer, duplicate evidence, self-reference and unknown error; no output repair | DONE |
| P1 | Live follow-up | Fresh exact plan after verified diagnostics; retain consumed run and old failure | IN PROGRESS |

### 4. Systematic Expansion

Responses and structured-model error mapping should be audited separately for
the same safe-but-unactionable failure mode. No broad retry loop or weakening of
verdict validation was introduced. The new classification is an observability
repair, not evidence that the rejected QA report is now valid.

### 5. Knowledge Capture

Updated responses-wire spec and this task's design/continuation notes. No template
tree exists here. Task remains unfinished; no commit, archive or business merge.
Validation: 89 CLI/Responses/diagnostic/Console tests passed; CLI 38 tests rerun,
Ruff, strict mypy and diff check passed.

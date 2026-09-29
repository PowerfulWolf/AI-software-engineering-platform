# Bug Analysis: pre-execution failure wrongly treated as interrupted Coder

## 1. Root Cause Category

E（隐含假设）+ B（跨层契约）+ D（测试缺口）。`candidate=None` 被等同于“存在可恢复 Coder”，
没有考虑已经创建 Task 但尚未成功编译第一个 Context 的窗口。

## 2. Why Earlier Fixes Did Not Restore the Old Requirement

349f971 修复了后续 Context 构建预算与完整证据，但没有 reopening terminal Task。
当时 review 已说明需要单独受审计 successor 路径；后续解释漏看这项存量限制，误建议普通继续。
0cd980b 的 Manager 变更没有改动旧恢复入口；这不是已完成需求突然被新代码破坏的证据。

## 3. Prevention Mechanisms

| Priority | Mechanism | Action | Status |
| --- | --- | --- | --- |
| P0 | Typed boundary | 独立 restart plan，不伪造 Coder/candidate evidence | DONE |
| P0 | End-to-end regression | 真实 Git/MySQL，精确旧事件形状，原需求完成且历史不变 | DONE |
| P0 | Authorization | 绑定源/父/基线/配置/Context budget，错摘要拒绝 | DONE |
| P1 | Restart durability | 测试 dispatch/attachment 中断，重开 Host 不重复执行 | DONE |
| P1 | Downstream coverage | 新 Task 后续 Coder/QA 失败仍可走原生恢复 | DONE |
| P1 | Existing-data handoff | 列明原需求 ID、只读证据和逐步恢复流程 | DONE |

## 4. Systematic Expansion

恢复入口必须区分无 Task、未调用角色、运行中断、已有候选、已独立验证五种事实。
上游 Product/Design/Plan 和 Task 内部 PLANNING 也不是同一阶段。
不能仅用顶层 BLOCKED/无候选来推断执行历史。新增状态分支需要同时检查 Console、
父子 journal、allocation ancestry、restart context 和 evaluation，不能只测一个 service。

## 5. Knowledge Capture

已更新 core/delivery-recovery.md 的签名、源事实矩阵、恢复顺序、禁止模式与测试点；
同步 docs/architecture/contracts.md 和 docs/operations/delivery-recovery.md。
仓库无 src/templates/markdown/spec 镜像，无需模板同步。

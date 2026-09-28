# Goal

让现有“设置保存交互优化”需求通过独立 QA/Reviewer 真正完成交付，并修复过程中遇到的平台缺陷。直接修改当前平台主工作区，不新建 worktree，不派发子代理。

## Latest requested correction and outcome (2026-09-28)

业务需求已由 ASE 正常完成：operation_631cb34a7404c76156e907dd37504d32 SUCCEEDED，
原联合需求 DONE，候选 9ac7c9ee830df548571db55ec5cf809e613467ba。四项 QA PASS、独立
Reviewer APPROVE；未 merge/push，未手工修改状态或业务代码。

用户明确要求修复仍然存在的 Reviewer-only 恢复粒度缺口。本轮验收：独立 QA PASS 后，
Reviewer 入场前后中断均可在新精确批准下只重跑 Reviewer；连续中断和重启仍可恢复；
不得重复 QA/业务 Coder、补造原 Task 事件或部分完成记录。较新否定结论、候选/验收范围变化、
缺失/篡改来源证据必须拒绝旧 PASS 复用；审批前端展示精确 QA 来源和 Reviewer-only 范围。
完成本平台修复后不要再触发已 DONE 的业务需求。

## Authoritative role boundary (2026-09-27)

用户再次明确：Codex 只控制和修复 ASE；业务代码由 ASE Coder 实施，独立 QA/Reviewer 验收。
Manager 对整个团队需求推进负责，必须识别环境/数据/权限/能力前提，提出可执行解决方案，
通过 typed 能力协调执行或请求人工，并跟进恢复；不能只报错后把责任交给外部操作员。
Codex 受用户委托评审 Manager 的人工审批，通过正常平台入口批准授权范围内的精确方案。
平台夹具测试只验证 ASE 能力，不能成为业务候选的 QA verdict 或替代 Manager 的正式运行记录。

## Confirmed facts

- 用户连续两次批准验证计划，但每次操作 SUCCEEDED 后又返回另一份审批。
- 三份计划的候选、Task、dispatch、approved stage、policy 完全相同，只有父 checkpoint 和新 execution identity/time 改变。
- Host 在生成子计划后无条件调用 joint resume；它追加父 checkpoint，破坏刚生成计划的 exact parent binding。
- 真实候选为 `fb76942771f79cecd9ae887961c8bb570c52046b`。已有 Task/审批/失败历史必须保留。
- 现有 joint scope recovery 测试复现了批准后不执行，38 秒失败于获批目标 preparation 未被采用。

## Requirements and acceptance

1. 等待 verification/recovery/scope 审批不得无意义推进父 journal；重复查看/继续复用仍有效的 exact plan。
2. 真实子 checkpoint 前进后先正常同步父观察值，再生成绑定新父 checkpoint 的计划；真实漂移仍拒绝旧批准。
3. 精确批准后真实执行；保留历史失败、独立角色、不可变证据和 at-most-once admission。
4. 自动化覆盖 proposal → repeat → approve → QA/Reviewer → parent DONE，以及后继恢复、父游标滞后和真实漂移。
5. 重启当前主工作区服务，通过正常 Console Operation 恢复现有需求；仅在真实 QA PASS、Reviewer APPROVE 和父需求 DONE 后宣称交付完成。
6. 真实 QA 运行暴露 Responses HTTP 400。修复 strict 工具参数不完整的 Schema，并保留受限、脱敏 HTTP 错误详情，Console 将 AgentRunFailed 映射为明确 MODEL_* 错误，不再掩盖为 MANAGER_FAILURE。

## Live evidence

- 修复后 proposal Operation `operation_aeec5a639c3a554d58ed7ee54b88c3e3` 保持父 digest `6c8d2e…`；新计划 `d5542693…` 的 inputs/definitions/policy 与用户授权的旧计划完全相同。
- 精确批准 Operation `operation_b76dbdce496eb9b0e305e2f35c82ae39` 确实进入 QA，Run `run_a77fcc9b52024f10910b373d0d7e6d3e` 返回 `PROVIDER_ERROR: Responses provider returned HTTP 400`。该 admission 已消费，不得重放。
- 后续潜在阻塞：历史 Swift RepositoryProfile 不识别 Package.swift，QA 仅有 Git 命令。已询问补齐 Swift/界面验证能力的授权，尚待用户答复。
- Operation `operation_1d4acbb6b049f83ad7aa6b3a56f2437e` 经新诊断明确返回 `MODEL_PROVIDER_ERROR / Previous response not found`：首轮已接受，但网关不保留 previous_response_id。工具循环改为官方支持的 store=false 完整输出/receipt 回传，不重放已执行工具。
- 最新真实验证 Operation `operation_c925f1e3f3fbf33d26cd4efa39420821` 已结束。Responses 路由返回 HTTP 504，配置内 Codex CLI 后备路由成功产出封存 QA 报告 `art_qa_761146a3180cf794bdef5cbd61dec781`；其结论是 FAIL，四项 criteria 均 NOT_TESTED，Finding 为 REQUIRED_VERIFICATION_UNAVAILABLE（策略阻止 Swift 和 UI 验证）。Reviewer 未执行，父需求仍 BLOCKED，不能宣称 DONE。
- 上述结果生成 successor plan `ab1c78d5d8a84b64c74fdff389bd80f3591c487809332650a5415569ac32ee27`；该计划尚未批准。环境/权限未改变时不应继续盲目批准。
- 本机 `xcrun swift --version` 为 Swift 6.3.3，`xcode-select -p` 指向 CommandLineTools；仅做只读探测，未安装依赖/访问账号。需要另行授权受限 Swift/XCTest/构建及 UI/辅助功能验证；UI 验收还需要两个登录账号及趋势样本，不能伪造数据或降低验收标准。
- 新增修复：RETRY_VERIFICATION 结果保留前次 completion digest、QA 报告 ID 和 NOT_TESTED/ERROR 数量；Console 不再把这段信息覆盖为普通“批准验证”。历史 Operation 不回写；后续普通计划查询提示先解决未完成验证的环境/权限问题。

## Boundaries

不直接改 Task 状态或 verdict，不删除历史，不跳过人工范围审批，不自动合并业务候选或部署。新的审批范围/外部环境要求超出授权时明确请求用户决定。

## Authorization and environment correction (continuation)

用户已答复“授权，继续”，允许受限 Swift/XCTest、构建和 UI/辅助功能检查，不再等待这份授权。
不包含依赖或完整 Xcode 安装。现有机器仅 CommandLineTools；`import XCTest` 和查找 `xctest`
均失败。此前业务主分支上的 test/CoreVerification 探针不是候选 QA 结果，不能作为验收证据。
补充验收：旧 Git-only 计划不能获得新权限；正常 Continue 应返回新 exact plan，历史事实不变。

用户随后明确确认“没有 xcode 和 xctest”，并允许 UI 验证“直接用真实数据”或“mock 数据”。
优先隔离 Mock 验证 UI 交互，报告必须区分 Mock 与真实登录链路；不复制凭据、不改真实历史。
这不授权安装工具链，也不意味着取消原验收项目或允许把未执行项目标为 PASS。

候选 `fb769427…` 为 Swift Package（只有 `Package.swift`）。因此 Xcode 如果未来安装，只是提供
可能的宿主工具链；不会自动成为 ASE 的项目能力。要沉淀为能力，必须由 ASE 版本化记录检测结果、
受限命令、角色权限、上下文和 evidence，并重新生成/批准精确计划。当前已沉淀的是受限 Swift
Package 能力，未接入 `xcodebuild` 或任意脚本能力。

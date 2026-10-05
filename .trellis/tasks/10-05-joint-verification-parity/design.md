# 实现方案

联合 Designer publication 与原生 Designer conversion 复用同一 AcceptanceDesignMapping。
校验不加到历史 model validator/validate_for；新产物在进入 Planner 前拒绝，原设计 bytes/hash 和
global acceptance ID 进入反馈，有限重试不删除原测试层级。拒绝历史贯穿同一已批准 Product、
scope 与 preparation 下尚未接纳新设计的纠错过程，包括知识等待和公开 recheck。recheck 不是
降低验证义务的批准，三轮“删 integration → 新 feedback → 再次提交”不能洗掉原要求。
Designer payload 显式带 required_verification_corrections，保留原 unit、验收映射和必需层级。
原生失败 receipt 的具体安全中文原因透传到交付 checkpoint，避免泛型 handoff 错误遮盖根因。

已封存问题只在有真实FAILED INVALID_OUTPUT原生Designer receipt、无commit marker、完整
parent/native history从未有Task/dispatch/候选/接纳交接、源/准备/产品批准/请求/上下文input
精确匹配时允许工程职责的普通CONTINUE。ProductionUnstartedDesignVerifier只读现有typed
stores和既有基线worktree，纯重算context/command摘要；不构造Host/preparer/model/SQLwriter。
在journal lock内追加DESIGNING successor，旧Design作为feedback、旧Plan/child留在history；
当次只清当前stage产物引用，原Product approval、预算与范围不改。正常Designer和Planner产出
新绑定，然后原生NEW Task→Coder→QA→Reviewer。其他INVALID与任何已有执行work均不放开。

没有新的 wire 字段、产品技术审批或模型权限；新增 proof 仅内部 typed DTO。公开入口继续由
Manager 绑定 exact checkpoint，locked service 重验当前 proof。Host 的恢复入口先只读
journal.current 识别窄纠错；这类 checkpoint 的 status 也不 reconcile。因此 Console 的 exact
checkpoint 前置检查不会重新创建丢失的 baseline 或制造 proof 输入。完整 proof 只在真正
CONTINUE 时验证；普通恢复保持既有 reconcile 路径。回滚保留所有事实；旧版本不能理解新接续
则应升级，不改封存历史绕过验证。

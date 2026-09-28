# 全生命周期可靠性设计

## 边界

保留现有领域模型和生产入口。Manager 协调人、环境、权限、知识与团队进度；确定性服务执行
检查、事务、租约和状态迁移；业务 Coder、QA、Reviewer 独立产出证据。Console 只呈现这些事实，
操作成功不等于交付成功。平台维护者只修 ASE，不替业务团队写实现或验收报告。

## 审查方法和架构调整

逐阶段检查入口 → 已批准输入 → 执行身份/权限 → durable commit → 下游输入 → 等待/失败/重启。
在各阶段的真实公共入口补测试，先看到失败，再修公共契约；不堆叠异常分支或引入另一套状态机。
不要求不现实的全笛卡尔积，优先历史数据与重启、租约与外部副作用、审批与候选变化的组合。

### 首个确定缺陷：恢复上下文分叉

`multi_directory/production.py:_derived_backend` 提供封存父需求和项目原生规则；
`recovery/resume.py:_run_remediation` 首次执行只补父上下文，原生规则未同源组装。
统一成一个纯来源投影，由新派发、修复首次运行和重启恢复共同调用。当前 target preparation
仍负责修复计划的当前事实校验，不能为了统一上下文把旧 preparation 偷换成新计划输入。

### 历史兼容

分开历史检索快照与当前批准的角色上下文。原 gap、resolution、snapshot、context 和 dispatch
摘要不改写。仅对同 Task/角色/候选且已验证归属的旧 continuation 允许兼容：历史 context 内
已封存的 baseline 明确引用原生文档 URI/hash，但旧检索快照漏掉文档正文时，可补全角色上下文，
检索仍使用原 snapshot。必须证明现有文档未变，新增文档就是当时已引用的规则；普通新增选择、
文档改写、未知来源、跨 scope、缺失历史证据全部拒绝。审批解答不是通用执行授权。
具体测试证实可行后才采用，不能只解除 `LEGACY_KNOWLEDGE_SCOPE_CHANGED` guard。

## 数据与兼容

### 已证明的其他契约缺陷

- 知识范围必须做交集：ContextSource 的角色限制贯穿 nested baseline/context.team/native document，
  foreign repository spec 不得因过滤结果为空变成 wildcard。意图模型看到的元数据与检索正文使用
  同一可见性投影；ORCHESTRATOR 不映射为任意 TeamRole。
- Product 外部调用返回后、任何 receipt/effect 写入前重读 checkpoint，拒绝并发人类回复后的旧结果。
  与 Designer/Planner 同层 guard 对齐；最终 store lineage 拒绝不是充分的 stale-result 防线。
- 普通交付 QA/Reviewer 按角色和 delivery attempt 绑定工作区与 adapter，每次调用重新校验候选和
  clean 状态；角色按需独立打开，消除必须同时存在的目录假设。旧现场原样保留，独立候选验收和
  Coder 延续的 attempt-01 语义不变。详见 verifier-worktree-lifecycle spec。

优先不改 wire schema、不新增状态、不迁移生产 SQL。若后续发现必须变更 wire contract，先补
历史序列化/摘要兼容说明和 Schema parity，再实现。保留当前真实需求 candidate/checkpoint。

## 发布与回滚

本任务不部署、不重启生产 Host、不推进真实需求。按切片记录新增文件和变更位置；回滚只撤本轮
增量，不 reset 工作区、不删旧事实。未来恢复前确认代码与运行版本一致、无并发执行者，再由正常
Manager 入口恢复；精确审批若因新事实失效，必须重新提案，不能复用旧批准。

## 用户确认恢复后的补充（2026-09-27）

用户已确认先完成当前 ASE 交付。恢复暴露之前未覆盖的“父需求旧 preparation / 修复任务新
preparation”组合：不能将父需求封存的旧规范正文与新 Task 的 baseline 拼接。后续分配在
run_prepared_allocation 的公共边界，按已批准的 successor profile 精确 Git revision、长度和
SHA 重新取得已有 native source 正文，保留 URI/角色限制并脱敏；绝不读取 mutable HEAD。
旧 snapshot guard 不变。Manager 接到新 Task 的知识等待后，先按 durable child 重开 runtime，
不能继续使用接纳前的旧 preparation backend。详见 continuation-20260927-post-audit.md。

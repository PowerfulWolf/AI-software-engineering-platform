# 新建需求的 Git 基线校验

## 现象与原因

选择未受 Git 管理、或已 `git init` 但没有提交的目录时，旧版本可能只显示
`Manager rejected the operation; inspect current delivery facts.`。

目录发现会如实记录 `DirectoryUnit.base_revision=None`。旧流程先保存 PREPARING，再准备
Repository，最后才检查 Git 基线。准备结果写入下一 checkpoint 时，`to_wire()` 省略 null
字段，而 `base_revision` 是必填的 nullable 字段，导致 Schema 校验先失败。其错误正文超过
Console 的 500 字符安全上限，于是被通用提示替代；原有 Git 前置条件提示未执行到。

## 边界契约

- `require_git_baselines(scope: DirectoryScope) -> None`：所有 unit 必须已有非空提交基线。
  缺少时抛出 `RequirementGitBaselineRequired`，不执行 prepare、模型或代码写入。
- 新 intake 在创建需求 journal 前校验；历史 PREPARING 在 reconcile/prepare 前使用同一校验。
- 历史 PREPARING 缺基线时，`status()` 只返回经过完整性校验的原 checkpoint，不触发
  reconcile，也不要求源码目录仍存在；继续交付才检查基线并返回可操作错误。
- Console 映射为既有 Operation envelope 的 `GIT_BASELINE_REQUIRED`，显示有界目录和中文
  原因/恢复指引。`error_summary` 不超过 500 字符；无 Schema、状态机或权限变更。
- Git 非仓库、Git 无有效 HEAD、旧需求未冻结基线三种情况分别说明。未知异常仍使用现有
  安全摘要，不能通过移除长度限制或暴露完整 ValidationError 修复此问题。
- 有提交的仓库及仓库内模块保留原行为，源码漂移/dirty checkout 守卫继续生效。
- `base_revision=None` 仍是有效的只读 discovery/历史事实；不可通过伪造提交 SHA 或
  修改整个领域序列化策略掩盖缺少基线。

## 验证矩阵

| 输入 | 结果 |
|---|---|
| 普通非 Git 目录 | `GIT_BASELINE_REQUIRED`，说明需要 Git 管理和首次提交 |
| 已初始化但没有 HEAD commit | 同一错误码，说明缺少有效提交 |
| 多目录中任一缺少基线 | 指明该目录，任何 Repository 准备前拒绝 |
| 有提交的根目录/模块 | 正常到 READY_FOR_DISCUSSION，零模型调用 |
| 历史 PREPARING/null baseline | 明确拒绝，不改 checkpoint 哈希/准备事实 |
| 源码已补提交，但旧 checkpoint 没有基线 | 说明旧需求缺少冻结基线，需要重新创建 |
| 路径过长 | 有界路径摘要仍包含原因，不退化为通用错误 |

## 存量数据处置

无需改库。失败 Operation 和 PREPARING checkpoint 是真实的失败历史，保留原文件与哈希；
不得改为成功，也不得给旧 checkpoint 补入当前 HEAD。准备阶段没有 Product/Coder 执行，
无需恢复 Agent 或业务代码。

1. 在原目录确认正确的 Git 根目录。若目录确实尚未纳管，由用户检查 `.gitignore`、敏感文件和
   提交范围后，初始化 Git 并完成首次提交；也可以重新选择已经有提交的正确仓库/模块。
2. 确认 `git rev-parse --verify 'HEAD^{commit}'` 返回提交，`git status --porcelain` 为空。
3. 使用原名称和修正后的目录重新创建需求。新的提交基线参与 Requirement identity，生成新的
   可讨论需求；旧失败需求保留审计历史。新建本身不调用模型。
4. 到 READY_FOR_DISCUSSION 后继续 Product 对话，并按原流程审批。

修复只改变输入拒绝和错误映射；回滚代码不需要迁移或重写历史记录。

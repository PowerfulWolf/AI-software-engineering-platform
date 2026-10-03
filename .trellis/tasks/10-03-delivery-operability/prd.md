# ASE delivery operability and blocker diagnostics

## Goal

让真实用户可以从 ASE Console/CLI 可靠地查看、理解和继续需求交付。平台必须保留安全门禁，同时把阻塞事实、当前阶段和下一步动作准确呈现为中文。

## Scope

- 根据 Delivery ID 自动定位唯一 Project，支持单仓和联合 Delivery 的 status/resume。
- 代码基线发生变化时保持旧 checkpoint 不可执行，提供稳定、可操作的基线漂移诊断。
- 对模型认证、限流、超时、上下文预算、非法 QA 输出、脏工作区和恢复审批等已知阻塞提供具体中文原因。
- Team View 使用最新活动子 Delivery/Task 的事实覆盖陈旧的 Manager 协调建议，并保持完整执行记录。

## Acceptance criteria

- [ ] 多 Project 且无默认 Project 时，`ase request status DELIVERY_ID` 能从唯一 sidecar 找到 Project；歧义时给出稳定中文错误。
- [ ] `status` 只读诊断不会修改旧 journal；基线漂移明确指出旧绑定 revision、当前 revision 和需要重新准备/精确恢复计划。
- [ ] `resume` 对基线漂移仍 fail closed，不能自动 rebase、覆盖 checkpoint 或重放审批。
- [ ] 真实历史中的主要阻塞原因在 Team View 显示具体中文解释，并保留安全的 run/evidence/digest 标识。
- [ ] 活动 Coder/QA/Reviewer 状态、终态阻塞状态和子 Delivery 最新 blocker 不互相覆盖错误。
- [ ] 增量测试、Ruff、格式检查、变更模块 Mypy 和 `git diff --check` 通过；不运行全量测试。
- [ ] 新增 failure mode 和存量数据处置写入 `.trellis/spec/`，旧 durable facts 字节保持不变。

## Risks and rollback

状态读取和展示属于 read-side 兼容改动；任何状态机或审批事实不变。回滚平台提交并在无活动角色时重启服务即可，保留已有 sidecar、Task、artifact、verdict 和审批记录。

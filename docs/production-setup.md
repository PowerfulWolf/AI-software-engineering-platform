# Production Team Host：部署与使用

本文描述 T034 之后的正常项目交付入口。平台管理员配置一次组织 Team Host；之后用户只提供目标 Git
项目绝对目录和自然语言需求。底层 `ase task ...` 不属于这条日常路径。

## 1. 运行边界

```text
目标项目（代码与原生规范）
        │
        ▼
ase project start / reply / approve / resume
        │
        ▼
OrganizationTeamHost
  ├── MySQL：Task、StateEvent、dispatch authority
  ├── organization workspace：AgentProfile、ModelPolicy、跨项目事实
  ├── project sidecar：需求、设计、计划、Context、Artifact、Evidence
  └── Git worktrees：Coder、QA、Reviewer 的隔离 checkout
```

平台不会向目标项目写入 `.ase`、数据库、Agent 记忆或日志。Coder 的业务变更只发生在独立分支/worktree；
QA、Reviewer 在同一 candidate commit 的独立 worktree 中验证。主 checkout 不会被自动合并或部署。

## 2. 前置条件

- Python 3.12+ 和 `uv`；
- Git，目标项目必须有干净工作树和已提交的 HEAD；
- Docker + Compose，或一个可连接的 MySQL 8.0；
- 默认 GPT-5.5 路由需要已安装并登录的 Codex CLI；
- 可选 Qwen/DeepSeek fallback 需要相应 Responses-compatible endpoint 和 API key。

安装平台依赖：

```bash
uv sync
uv run ase --version
codex login status
```

如果 `codex login status` 未登录，先执行 `codex login`。平台不会读取或保存登录凭据正文；Codex CLI 自己
管理当前账号会话。

## 3. 启动独立 MySQL

本地开发配置不会探测或复用其他项目容器：

```bash
cp .env.example .env
docker compose up -d mysql
docker compose ps
```

默认服务绑定 `127.0.0.1:3307`，容器名为 `ase-mysql`，数据卷为
`ai-software-engineer-mysql-data`。`.env` 会被 Compose 读取，但不会自动导出到运行 `ase` 的 shell；仍需：

```bash
export ASE_MYSQL_DSN='mysql+pymysql://ase:ase_local_change_me@127.0.0.1:3307/ai_software_engineer'
```

这些默认密码只能用于 loopback 本地开发。正式部署应使用独立 MySQL 用户、强密码和 secret manager，
并对 DSN 中保留字符做 URL percent-encoding。Team Host 启动时会验证连接并幂等初始化表；数据库停止、
认证失败或 schema 不兼容都会 fail closed。

停止容器不会删除数据：

```bash
docker compose stop mysql
```

不要用 `docker compose down -v`，除非明确要删除本项目的 MySQL 数据卷。

## 4. 配置组织 Team Host

配置契约见 [`schemas/production-config.schema.json`](../schemas/production-config.schema.json)，示例见
[`config/production.example.json`](../config/production.example.json)。默认读取：

```text
~/.config/ai-software-engineer/config.json
```

初始化：

```bash
mkdir -p "$HOME/.config/ai-software-engineer"
cp config/production.example.json \
  "$HOME/.config/ai-software-engineer/config.json"
```

至少修改两项：

```json
{
  "platform_root": "/absolute/path/to/ase-data",
  "live_model_execution": true
}
```

`platform_root` 是平台外置数据根，必须为绝对路径，不应位于任一目标项目中。配置中只记录 DSN/API key
的环境变量名，不能写 secret。若配置文件位于其他位置：

```bash
export ASE_CONFIG='/absolute/path/to/production.json'
```

`live_model_execution=false` 是示例文件的安全默认值；它会明确拒绝真实模型运行，不会偷偷切换 fake
Agent。

## 5. 模型路由

`model_routes` 的数组顺序就是冻结后的尝试顺序。示例配置的初始顺序是：

1. `codex / gpt-5.5 / codex_cli`；
2. `qwen / YOUR_QWEN_MODEL / responses`（替换占位符并显式启用后）；
3. `deepseek / YOUR_DEEPSEEK_MODEL / responses`（替换占位符并显式启用后）。

Codex 路由不接受 endpoint 或 API key 字段。Responses 路由必须同时配置 `endpoint` 和
`api_key_env`，例如 `DASHSCOPE_API_KEY` 或 `DEEPSEEK_API_KEY`；密钥本身只存在于进程环境。
Qwen/DeepSeek 的模型 ID 和 endpoint 必须以相应账户当前实际支持的值替换；平台不会猜测“免费”型号，
也不把某个供应商的试用额度当成模型固有属性。

只有额度耗尽、rate limit、timeout 或临时 provider unavailable 会触发下一路由。认证失败、无效 JSON/
Artifact、policy violation、产品歧义或规范冲突不会靠换模型掩盖。每次 delivery role 路由尝试都会以
脱敏事实写入项目 sidecar，可在恢复时重放。上游 Product/Designer/Planner 已完成的 stage artifact 会
直接复用；当前仍存在“provider 已返回但 stage artifact 尚未落盘时进程崩溃可能重复计费”的小窗口，
这是后续 durable upstream-attempt ledger 的工作。

模型是某次 AgentRun 使用的“大脑”，不是 Agent 身份。Coder、QA、Reviewer 始终是三个不同的组织
Agent，即使它们碰巧使用同一模型也不能互相代替或自我批准。

## 6. 日常交付

### 6.1 开始并讨论需求

```bash
uv run ase project start /absolute/path/to/target-project \
  --title "订单取消" \
  --requirement "允许用户取消未支付订单，并补充自动化测试"
```

返回值是可机器读取的 JSON。根据 `checkpoint.stage` 行动：

| Stage | 含义 | 用户动作 |
|---|---|---|
| `WAITING_PRODUCT_REPLY` | Product Agent 仍缺少重要业务决策 | 读取问题并执行 `project reply` |
| `WAITING_PRODUCT_APPROVAL` | ProductSpec 已可评审 | 阅读 `product` 后执行 `project approve` |
| `WAITING_HUMAN` | 规范冲突或安全边界需要人类决定 | 检查 `failure_code`、`failure_summary` 和 sidecar 证据 |
| `DONE` | candidate 已通过 QA/Review | 人工复核 candidate 后决定合并 |
| `BLOCKED` / `FAILED` | 自动路径不能安全继续 | 保留现场，按失败证据修复配置或需求 |

补充产品信息：

```bash
uv run ase project reply delivery_xxx \
  --checkpoint <checkpoint_sha256> \
  --message "取消仅允许在未支付状态；操作需要记录审计日志"
```

批准 ProductSpec：

```bash
uv run ase project approve delivery_xxx \
  --checkpoint <checkpoint_sha256> \
  --approval-reference "change-request-123-approved"
```

CLI 的 `approve` 是 v0.1 的可信人工通道。它只批准返回值中 exact ProductSpec 的 ID + digest；旧
checkpoint 会被拒绝。

### 6.2 查看和恢复

```bash
uv run ase project status delivery_xxx
uv run ase project resume delivery_xxx
```

每个 CLI 命令都是独立进程。`status` 从 append-only checkpoint 读取当前事实；`resume` 先对照 Git、
MySQL 和 sidecar 重算，不匹配就停止，不会覆盖现场。

### 6.3 检查候选变更

成功输出包含：

```text
checkpoint.stage = DONE
checkpoint.task_id = task_...
checkpoint.task_status = DONE
checkpoint.candidate_revision = <40-char commit SHA>
```

复核候选：

```bash
git -C /absolute/path/to/target-project show <candidate_revision>
git -C /absolute/path/to/target-project diff HEAD..<candidate_revision>
git -C /absolute/path/to/target-project branch --contains <candidate_revision>
```

候选通常保留在 `ai/<task-id>/attempt-1`。平台不执行 merge；确认无误后，由项目自己的保护分支流程、
PR 或人工 Git 命令完成交付。

## 7. 数据位置与恢复责任

```text
<platform_root>/
├── organization/                 # 组织 AgentProfile、ModelPolicy、跨项目事实
├── projects/<project-id>/        # 每个项目唯一 sidecar
    ├── workspace.json
    ├── profile/ knowledge/ policy/ state/
    ├── contexts/ artifacts/ evidence/ evaluations/
│   └── handoffs/ runs/ logs/ assignments/
└── worktrees/<project-id>/       # 当前/保留的角色 worktree
```

MySQL 和整个 `platform_root` 都是恢复所需数据，应一起备份。不要只备份目标 Git 项目。干净 worktree 可
回收；dirty/漂移 worktree 会保留给人工取证。

## 8. Live smoke

[`scripts/smoke-live-gpt55.sh`](../scripts/smoke-live-gpt55.sh) 使用临时 Git 项目验证 Production Team
Host、GPT-5.5、Product gate、隔离 Coder、QA 和 Reviewer。它会消耗真实额度，因此默认拒绝运行：

```bash
ASE_RUN_LIVE_TESTS=1 scripts/smoke-live-gpt55.sh
```

脚本不 merge、不删除现场。Product Agent 若要求澄清，脚本会停止并打印保存位置；这不是伪造失败，
而是产品门禁按设计生效。默认 pytest/CI 不运行 live 模型。

请从普通本地终端运行该脚本。若在一个已经受 macOS `sandbox-exec` 约束的 Codex 任务内部再次启动
Codex CLI，内层 workspace sandbox 可能因操作系统禁止嵌套而返回 `sandbox_apply: Operation not permitted`。
这属于验收宿主限制，不代表目标项目失败；Production Team Host 不会为了规避它自动降级到
`danger-full-access`。离线 scripted-provider E2E 仍会使用真实 MySQL、Git commit 和隔离 worktree 验证
完整 `DONE` 流程。

## 9. 当前限制

- 单个 Task 仍固定串行 `Coder → QA → Reviewer`，没有复杂 DAG；
- 当前 production delivery 每个角色只尝试一次；无法安全继续时进入人工处理；
- Codex CLI 的 Coder 隔离由 Git worktree、Codex sandbox 和运行后 changed-path/commit 校验共同提供，
  不是容器级强隔离；
- HTTP Responses tool loop 只执行 allowlist 命令，但 v0.1 也不是容器级 OS sandbox；
- 不自动 merge、deploy、处理数据库迁移或跨仓库事务；
- T033 Reporter 暂停，当前用户交付是 typed JSON、candidate commit 和证据，而不是自动生成报告；
- PostgreSQL repository adapter 保留为后续 TODO，当前生产实现固定 MySQL 8.0。

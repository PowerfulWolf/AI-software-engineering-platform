# Production Team Host：部署与使用

平台管理员完成一次 bootstrap；之后用户从本地 Web Console 创建或选择 Project、创建 Requirement、
选择一个或多个代码目录，平台准备 Team、Project 与 Repository 规范后再讨论需求。底层
`ase task ...` 不属于日常路径。

日常交付采用[平台操作与问题反馈闭环](operator-feedback-loop.md)：用户在平台执行，开发协作者
定位并修复具体报错，验证后交回用户继续交付。

## 1. 运行边界

**Team Host 是团队运行的装配入口，不是一个 Agent，也不是 Docker 容器。**
它读取 Team 配置，连接并初始化 MySQL，打开唯一 Team workspace 与 sibling Project registry，
把模型适配器、Manager 工作流及隔离交付服务连接起来，提供给本地 Web Console 使用。
Manager 负责推进工作；Host 负责让这些能力能够实际运行。

`ase-console` 是当前推荐的常驻本机进程，Host 作为其中的 Python 组合对象存在；兼容 CLI
仍会为一次诊断命令重新装配 Host。进程退出后，工作进度保存在 MySQL 和外置 workspace，重启后
读取事实继续。因此“长期团队”指 Team 身份和工作记录持久化，不代表模型调用永远占用进程。

```text
目标 Repository（代码与原生规范）
        │
        ▼
浏览器：Project / Team 知识 / 设置 / Requirement 与交付
        │
        ▼
ase-console → TeamHost
  ├── MySQL：Task、StateEvent、dispatch authority
  ├── team/：AgentProfile、ModelPolicy、通用知识、工作项与租约
  ├── projects/<project_id>/：Project 知识、Repository sidecar、Requirement 记录
  └── Git worktrees：Coder、QA、Reviewer 的隔离 checkout
```

平台不会向目标项目写入 `.ase`、数据库、Agent 记忆或日志。Coder 的业务变更只发生在独立分支/worktree；
QA、Reviewer 在同一 candidate commit 的独立 worktree 中验证。主 checkout 不会被自动合并或部署。

## 2. 前置条件

- Python 3.12+ 和 `uv`；
- Git，目标项目必须有干净工作树和已提交的 HEAD；
- Docker + Compose，或一个可连接的 MySQL 8.0；
- 默认 Codex CLI 路由需要已安装并登录的 Codex CLI，具体模型以当前配置为准；
- 可选 Qwen/DeepSeek fallback 需要相应 Responses-compatible endpoint 和 API key。

安装平台依赖：

```bash
uv sync
uv run ase --version
codex login status
```

直连 Codex CLI 或仅配置代理地址时，如 `codex login status` 未登录，先执行 `codex login`。
页面填写代理 API Key 的模式不依赖该登录。平台不会读取 Codex CLI 登录凭据正文。
如果在“设置 → 模型路由 → Codex CLI 连接”配置了本机 CLIProxyAPI 地址，平台的 Codex CLI
路由改为显式使用该代理。可在同一区域填写代理 API Key：它和 MySQL DSN 一样仅写入本机
`runtime.env`（0600），配置 JSON 只保存固定环境变量名，页面/API 不回显密钥。保存后应用配置重启；
CLI 会通过固定 `env_key` 从进程环境获取它，不需要改动个人 Codex 登录。
如果只配置代理地址而不在页面填写 Key，则沿用同一 Codex 登录环境的
`codex login --with-api-key`。CLI 当前是 ChatGPT 登录且令牌已撤销时，
`codex login status` 仍可能显示“已登录”，并不证明密钥或刷新仍有效。切换登录方式前请注意：
默认 CLI/IDE 共享登录缓存；`codex logout` 会清除现有缓存。由操作者在与服务相同的系统用户、
`CODEX_HOME` 下运行（变量名仅作示例，不要把密钥写进命令行参数或仓库）：

```bash
codex logout
printenv CLIPROXY_API_KEY | codex login --with-api-key
codex login status
```

若需要隔离个人 ChatGPT 登录，应另用专门的 CLI 凭证存储环境；本设置不会自动迁移或复制现有凭证。

## 3. 启动独立 MySQL

本地开发配置不会探测或复用其他项目容器：

```bash
cp .env.example .env
docker compose up -d mysql
docker compose ps
```

默认服务绑定 `127.0.0.1:3307`，容器名为 `ase-mysql`，数据卷为
`ai-software-engineer-mysql-data`。`.env` 只供 Compose 创建数据库；平台连接串在 Web Console
“设置”中填写：

```text
mysql+pymysql://ase:ase_local_change_me@127.0.0.1:3307/ai_software_engineer
```

这些默认密码只能用于 loopback 本地开发。正式部署应使用独立 MySQL 用户、强密码和 secret manager，
并对 DSN 中保留字符做 URL percent-encoding。Team Host 启动时会验证连接并幂等初始化表；数据库停止、
认证失败或 schema 不兼容都会 fail closed。

停止容器不会删除数据：

```bash
docker compose stop mysql
```

不要用 `docker compose down -v`，除非明确要删除本项目的 MySQL 数据卷。

## 4. 配置 Team Host

配置契约见 [`schemas/production-config.schema.json`](../schemas/production-config.schema.json)，示例见
[`config/production.example.json`](../config/production.example.json)。Web Console 默认读取：

```text
~/.config/ai-software-engineer/config.json
```

该文件不存在时，Web Console 使用页面可见的内置默认值并进入 setup 模式，不会自动写文件；MySQL
尚未配置也不妨碍打开“设置”和“状态”。用户第一次保存才创建配置文件。已有文件损坏或不合法时仍
会拒绝启动，不会用默认值覆盖。需要预先定制或使用兼容 CLI 时，也可以手工初始化：

```bash
mkdir -p "$HOME/.config/ai-software-engineer"
cp config/production.example.json \
  "$HOME/.config/ai-software-engineer/config.json"
```

至少确认 Team 身份和模型执行开关。macOS/Linux 使用默认 `~/.ase` 时无需填写
`platform_root`，只有自定义数据根时才添加该字段：

```json
{
  "schema_version": "v0.2",
  "team_id": "team_ai",
  "team_name": "AI Team",
  "default_project_id": null,
  "default_project_name": null,
  "live_model_execution": true,
  "console_port": 8765
}
```

`platform_root` 是平台外置数据根，不应位于任一目标项目中。在 macOS/Linux，省略它会解析为当前用户的
`~/.ase`；解析不依赖当前工作目录，也不会创建该目录。显式绝对路径优先于默认值，且安全的 `~/custom-ase`
会先展开为当前用户主目录下的绝对路径。相对路径、控制字符，以及绝对或 home-relative 路径中的
`..` traversal 都会失败关闭，
不会回退到默认目录。普通配置 JSON 只记录 DSN/API key 的环境变量名；设置页接收的完整值写入同目录
`runtime.env`，接口和页面不会读取回显。若配置文件位于其他位置：

```bash
export ASE_CONFIG='/absolute/path/to/production.json'
```

通过设置页切换到全新 `platform_root` 时，平台只在新根初始化当前 Team 身份；不会静默复制旧根的
Team 知识、Projects、Requirements 或 worktree。重启到新根后，应在新 workspace 重新导入并选择文档。

`live_model_execution=false` 是示例文件的安全默认值；它会明确拒绝真实模型运行，不会偷偷切换 fake
Agent。

`team_id` 默认为 `team_ai`。v0.1 只有一个长期 Team，它可以服务多个 sibling Project；Project 不复制
AgentProfile，也不代表单个 Git 仓库或一次 Requirement。
`team_name` 是首次注册的显示名；ID/名称与持久化 manifest 不一致时拒绝静默覆盖。
日常通过 Web Console 的“知识库”管理 Markdown、TXT、PDF 或 DOCX。页面默认展示已导入资产；
点击作用域对应的导入按钮后，在弹窗中一次选择多份文档。“团队通用知识”保存在
`team/knowledge/documents/<document_id>/`；“当前 Project 知识”保存在
`projects/<project_id>/knowledge/documents/<document_id>/`。两个作用域分别用同目录下的
`selection.json` 保存明确启用的文档；启停立即影响之后的新需求，不需要重启。兼容配置中的
`team_knowledge_paths` / `project_knowledge_paths` 只在 selection 文件尚不存在时作为旧入口回退；
不会递归自动发现文件。这些资料是只读上下文，不会自动覆盖 Repository 原生规范。
已准备 Requirement 依赖的 Team/Project 知识发生变化时，会拒绝继续旧交付，应检查变化并处理规范/上下文冲突。
默认配置不读取任何额外 Team 文档，也不会自动迁移其他 `platform_root` 数据。
Team、Project 和 Repository sidecar 目录只在显式的 Host 初始化、Project/Requirement 准备或交付写入流程中创建；加载配置和
`ase team serve` 等只读查看不会创建目录。

### 执行与重试策略

“设置 → 通用设置 → 执行与重试策略”按模型角色提供独立上限，保存并应用配置重启后生效：

```json
{
  "execution_retry_policy": {
    "product": {"max_attempts": 20, "max_transient_failures": 5},
    "designer": {"max_attempts": 3, "max_transient_failures": 5},
    "planner": {"max_attempts": 3, "max_transient_failures": 5},
    "coder": {"max_attempts": 3, "max_transient_failures": 5},
    "qa": {"max_transient_failures": 5},
    "reviewer": {"max_transient_failures": 5}
  }
}
```

每个输入均为 1–100 的整数。工作次数含首次执行：Product 包含讨论/产物调用，Designer/Planner
包含产物修正，Coder 包含实现、未完成续跑与 QA/Review 退回修复。临时故障上限指可记录的失败数，
达到上限便停止（配置 1 表示首次临时失败后停止）。只有 typed retryable 的超时、504/服务不可用、
限流与额度故障计入独立额度，包括角色调用前的知识咨询；未知中断不退款。

QA/Reviewer 的有效否定结论不在本角色重跑，而是交给 Coder；候选复核仍要求新计划及人工批准。
Manager 当前为确定性调度，没有模型额度。联合上游调用失败会结束当前操作，操作者可检查原因后
继续；Delivery 的重试必须取得新 Run 的真实 claim，不能在一个已消费 permit 内重复调用。

配置覆盖 Console/`ase request` 的 Product、Designer、Planner 以及生产新建 Task 的
Coder、QA、Reviewer。低层兼容 `ase project` 的原生上游 journal 不迁移到联合计数协议；
其旧上游恢复行为保持不变，日常需求请使用 `ase request`。低层手工创建的 Task 若无
`retry_policy` 也保留原 `max_attempts` 行为。

上游需求显示次数/上限，提高配置后可以继续，重启不清零。新 Task 在 dispatch 时冻结
`retry_policy`；已有 Task 不会随全局设置热改或自动解除终态。旧 `design_retry_policy` 可读并映射
到 Designer，保存输出统一为新字段；同时给出互相冲突的新旧配置会拒绝。新功能不追溯重算旧失败。恢复步骤见
[操作反馈闭环](operator-feedback-loop.md#design-预算耗尽与存量需求处置)。

## 5. 模型路由

`model_routes` 是平台的可用模型目录，不代表每个 Agent 都会自动使用其中所有模型。
示例配置的初始目录顺序是：

1. `codex / gpt-5.6-terra / codex_cli`；
2. `deepseek / YOUR_DEEPSEEK_MODEL / responses`（替换占位符并显式启用后）；
3. `qwen / YOUR_QWEN_MODEL / responses`（千问，替换占位符并显式启用后）。

即默认可选模型依次列出 GPT、DeepSeek 和 Qianwen（千问）。禁用的路由不可选；这不是
代码中按供应商名称强制排序。只有没有 `agent_model_routes` 的旧配置才会临时继承该全局顺序。

`agent_model_routes` 在这个可用模型目录之上，为 Manager、Product、Designer、Planner、Coder、QA、
Reviewer 分别保存可用目录的有序子集：第一项是该 Agent 的主模型，后续项是人工选择的
0–N 个备用路由。设置页可添加、移除、上移和下移备用模型；只是在目录中启用一个模型，
不会让它自动成为任何 Agent 的备用模型。可以让 Product 使用支持截图的模型、Coder 使用偏实现的模型、
QA/Reviewer 使用不同模型。
一条路由的完整身份是 `provider + model + reasoning_effort`；因此同一个模型可以同时配置 `medium`
和 `high`，并由不同 Agent 分别选择。完全相同的三项组合不能重复。
旧配置没有 `agent_model_routes` 时，所有成员继承全局启用顺序；一旦显式配置，就必须覆盖七个角色且
只能引用已启用路由。旧的 Agent 引用若缺少推理程度，只在 provider/model 唯一时兼容；存在多个推理
程度时会要求明确选择。Manager 当前只调用确定性 Skills，不直接发起模型调用，但仍保留完整策略。
升级前的交付 Artifact 若尚未记录推理程度，也只在 provider/model 唯一时允许恢复；系统不会把它们
静默当作 `medium`。新执行会始终记录完整三元组。

Codex 路由不接受 endpoint 或 API key 字段。Responses 路由必须同时配置 `endpoint` 和
`api_key_env`，例如 `DASHSCOPE_API_KEY` 或 `DEEPSEEK_API_KEY`；完整密钥可在设置页填写并由
`runtime.env` 提供给下次启动的进程。
`codex_cli_proxy_base_url` 是独立的可选本机 CLI 连接设置。例如 CLIProxyAPI 监听本机
`http://127.0.0.1:8317/v1` 时，在模型路由页填写这个 **base URL**，不要填 `/responses` 完整路径，
也不要在 URL 中放密码、query 或 fragment。只接受 `localhost`、`127.0.0.1` 或 `::1` 的
HTTP 地址。平台仍以
`--ignore-user-config` 启动 Codex，显式指定本地 `responses` provider，因而不会读取
`~/.codex/config.toml` 的 provider、hooks 或其他行为。填写页面 API Key 时，配置的
`codex_cli_proxy_api_key_env` 为 `ASE_CODEX_PROXY_API_KEY`，并使用 `env_key` 认证；仅配置
URL 时仍使用 `requires_openai_auth=true` 的 Codex 已保存登录。留空代理 URL 则沿用 Codex CLI
原有直连登录。代理 Key 只传给 Codex 客户端进程，CLI 工具 shell 的环境策略显式排除该变量；
不要把密钥放在目标仓库、模型提示、代理 URL 或命令行参数中。
该环境过滤只阻止 CLI 启动的工具 shell 继承此变量，不等于同一系统用户下的
`runtime.env` 文件不可读；此模式仅适用于可信本机操作者与可信运行环境。
保存后需“应用配置”重启 Host；代理不可用时不会静默回退直连。历史 504/登录错误事实保留，
修复连接后在需求页面显式继续现有需求，不必改库或重新批准已批准的 ProductSpec。
状态页的 Codex 就绪标记只确认 CLI 可执行文件可解析，不检测代理服务或模型请求是否可用。
Codex CLI 默认声明支持截图。Responses 路由只有在设置页显式启用“支持图片输入”后，才能接收 Product
截图；含截图的调用会跳过不支持图片的备用路由，而不是假装模型已经看过图片。
Qwen/DeepSeek 的模型 ID 和 endpoint 必须以相应账户当前实际支持的值替换；平台不会猜测“免费”型号，
也不把某个供应商的试用额度当成模型固有属性。

只有额度耗尽、rate limit、timeout 或临时 provider unavailable 会触发下一路由。认证失败、无效 JSON/
Artifact、policy violation、产品歧义或规范冲突不会靠换模型掩盖。每次 delivery role 路由尝试都会以
脱敏事实写入 Repository sidecar，可在恢复时重放。上游 Product/Designer/Planner 已完成的 stage artifact 会
直接复用；当前仍存在“provider 已返回但 stage artifact 尚未落盘时进程崩溃可能重复计费”的小窗口，
这是后续 durable upstream-attempt ledger 的工作。

模型是某次 AgentRun 使用的“大脑”，不是 Agent 身份。Coder、QA、Reviewer 始终是三个不同的 Team
Agent，即使它们碰巧使用同一模型也不能互相代替或自我批准。

生产 Host 会先按 Agent 角色冻结主模型/备用顺序，再由底层 ModelRouter 执行能力、额度和失败路由。
风险等级目前仍使用相同的角色策略，尚未实现按任务难度动态升降模型档位。

## 6. 日常交付

日常用户只需启动本地 Web Console：

```bash
./scripts/ase-console-service.sh start
```

用同一脚本的 `status`、`logs`、`restart` 和 `stop` 管理后台进程。更新代码后须执行 `restart`
再刷新浏览器；只刷新页面可能使新版静态界面连接到仍持有旧 Python 配置契约的进程，设置页会
提示服务版本不匹配并阻止保存。脚本解析 `ASE_CONFIG` 或默认
配置路径，自动加载同目录 `runtime.env`，并要求先执行过 `uv sync`。通常不再需要手工 export DSN
或 provider key。

多个代码检出目录默认共用同一个本机 Console 状态目录。PID 记录会同时保存进程号和实际启动它的
仓库可执行文件；从另一个已更新检出目录执行 `restart` 时，脚本只在命令行与记录身份精确匹配后
停止旧实例并切换到当前检出目录。无法验证身份时不会发送信号，也不会覆盖 PID 后另起重复实例。

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)，先在网页完成管理准备：

1. 在“设置”查看内置/已保存配置，按需维护平台目录、完整 MySQL DSN、模型路由/API Key、七个 Agent
   各自的主模型/备用顺序、Codex、执行开关和端口；用“测试连接”验证 MySQL；
2. 保存成功弹窗在配置需要重启时展示“应用配置”按钮，否则仅提示保存成功。点击弹窗内的“应用配置”
   可应用已保存设置；关闭弹窗后可再次保存打开入口。页面只提交空的 typed lifecycle 请求；服务脚本监督器
   验证受管进程后重建 Host，并在浏览器重连后重新读取状态确认已生效。也可执行
   `./scripts/ase-console-service.sh restart` 进行人工恢复；
3. 在“状态”确认 MySQL、Codex、Team workspace 和启用的模型路由已就绪；逐个检查七名 Agent 的
   主模型、备用顺序、Reasoning 和就绪情况，再用独立的“可用模型目录”检查 Provider/凭证；这些是
   配置状态，不代表 Agent 正在执行；
4. 在“需求与交付”创建或确认该业务上下文对应的 Project；
5. 在“知识库”先进入独立的“团队知识库”或“项目知识库”，再分别维护团队通用知识、项目背景知识和
   开发规范；页面默认只展示现有资产，通过“导入…”按钮打开弹窗并支持多文件选择。项目知识库还提供
   基于 QA/Review 证据的学习改进。上传、启用和选择都无需重启。

然后在“需求与交付”页完成：

1. 在同一页创建或选择 Project，再新建 Requirement；点击“选择代码目录”打开系统弹窗，一次选择一个
   或多个本地代码目录，并在提交前通过路径标签检查或移除；
2. 等待 Manager 完成注册、RepositoryProfile 发现和规范编译；
3. 在需求详情与 Product Agent 多轮讨论，可提交文字，也可直接在输入框粘贴最多 4 张 PNG/JPEG/WebP
   截图；页面按顺序保留双方消息。Product Agent 需要澄清时继续回复，ProductSpec 生成后可继续提出
   修改，也可进入批准；
4. 批准 ProductSpec，观察 Designer、Planner、Coder、QA、Reviewer 的串行进度；
5. 中断后点击“继续交付”；页面出现候选复核或 Coder 恢复计划时，阅读摘要后点击“批准并继续”；
6. DONE 后领取每个仓库的 candidate commit/branch 和 QA/Review 证据。

浏览器命令先在 `team/work-items/console-operations/` 写入 append-only Operation，
再由后台 Manager 执行。刷新或关闭页面不会取消已接纳的操作；Host 重启会把遗留 RUNNING
操作标成 INTERRUPTED，并要求用户基于最新 Delivery 事实重新“继续交付”，不会静默重放不确定调用。

`ase-console` 只监听 loopback。当前可信本机 MVP 为降低使用门槛，会把 DSN/API Key 以 `0600`
明文保存在配置目录的 `runtime.env`；不要提交或共享该文件，也不要把值写入 launchd plist 或
systemd unit。后续应以 macOS Keychain / Linux Secret Service 替换存储实现。

“应用配置”只作用于服务端判定为 `restart_required` 的已保存运行配置，不是热加载，也不适用于 Team/
Project 知识选择或 Spec activation。浏览器不能提交路径、命令、DSN、API key 或环境变量值；状态文件
只记录稳定请求 ID、`PENDING/SUCCEEDED/FAILED` 和固定安全摘要。重复点击归并到同一请求，监督器对同一
终态请求不会重复重启。启动失败或 20 秒内无法停止旧进程时，已保存的 `config.json`/`runtime.env`
保持不变，页面显示脱敏失败摘要；使用 `status`/`logs` 检查后可通过脚本人工 `restart`，脚本不会升级到
`KILL`，也不会向无法验证的 Console 或监督器 PID 发送信号。监督器记录并验证自身脚本身份；每次子
Host 启动都在隔离子 shell 中重新加载 `runtime.env`，因此已从该文件删除的密钥不会由监督器残留传递。
若保存的 Console 端口发生变化，页面会在请求被接受后跳转到同一 loopback host 的服务端有效端口；
该端口由服务端结合已保存配置与 `ASE_CONSOLE_PORT` 覆盖选择，浏览器不能提供主机或端口。页面只在
本地保存不透明请求 ID 与有效端口以便跳转或刷新后继续查询；必须同时读到匹配的 `SUCCEEDED` 状态和
`restart_required=false` 才确认成功。监督器仅在 lifecycle 状态精确匹配同一 `PENDING` 请求时才会
停止子进程，并以有界等待和属主条件清理避免旧监督器删除替换进程的 PID 记录。
浏览器等待重启有 30 秒上限；超时后保留不透明请求身份供后续核对，显示固定恢复指引并允许安全重试。
跨端口重连在同一上限内重复尝试。监督器以原子锁保证单一属主，并按精确参数验证进程；若已领取请求后
异常退出、`runtime.env` 格式错误或为符号链接，生命周期会收敛为脱敏 `FAILED`，不会永久停留在
`PENDING`。

<details>
<summary>兼容 CLI 与逐条诊断流程</summary>

### 6.1 开始并讨论需求（break-glass）

先为兼容 CLI 配置 `default_project_id/default_project_name`，再创建 Requirement。目录可以只传一个，
也可以传多个不相邻的 Repository 或模块目录：

```bash
uv run ase request create /absolute/path/to/backend /another/path/to/frontend \
  --name "订单取消"
```

创建不调用模型。所有目录准备成功后返回 `READY_FOR_DISCUSSION`，再用输出的 delivery_id 和
checkpoint_sha256 讨论需求：

```bash
uv run ase request discuss delivery_multi_xxx \
  --checkpoint <checkpoint_sha256> \
  --message "前后端支持取消未支付订单，并补充自动化测试"
```

`checkpoint.product_spec` 保存联合产品文档，`checkpoint.dialogue` 保存澄清问答；修订也使用
`request discuss`。可评审后只批准一次：

```bash
uv run ase request approve delivery_multi_xxx --checkpoint <latest-checkpoint-sha256>
uv run ase request status delivery_multi_xxx
uv run ase request resume delivery_multi_xxx
```

联合方案按仓库生成原生 Task；每仓依次完成 Coder、QA、Reviewer 后，平台在完整候选集合上
实际运行联合验收。`checkpoint.children` 给出每仓 Task/candidate；`checkpoint.integration`
保存候选集合、命令及结果。只有联合验收通过才报告整体 DONE。

测试通过环境变量 `ASE_UNIT_<unit-id 的大写 16 位 hex 后缀>` 访问候选目录，cwd 是所指定仓库
的候选根；不传入 Host secrets。测试必须存在于候选中、符合项目命令 allowlist；不能用 echo、
Git inspection 或无测试的成功退出冒充验收。平台保留独立候选，不自动 merge/push。

中断后复用已记录的阶段和原生子交付。每次 provider 调用使用独立 Run；已封存但结果不确定的
调用不会直接重放，`resume` 会要求批准新的验证计划。BLOCKED 且已有 candidate 时，`resume` 先做
独立 QA/Reviewer 复核；QA FAIL 或 Review REJECT 会保留旧 Task/candidate，并创建关联修复 Task 继续
Coder→QA→Reviewer。尚无 candidate 的失败 Coder 由 `resume` 自动发现和封存现场，批准精确恢复
计划后创建新 Task 接续；规范、权限、来源冲突仍需人工处理。
每个 Requirement 都保留创建时的代码、规范和知识基线。配置 checkout 的 HEAD、选定规范或知识之后
变化，只影响新 Requirement；旧 Requirement 继续从自己的 detached baseline 创建子 Task。只有该
需求的 retained commit/worktree 无法验证时才停止并要求恢复。平台仍不自动 merge；最终候选合入
最新目标分支时由人工或后续发布流程解决冲突。

下面保留原单仓一步式入口，方便兼容旧命令；新需求推荐上面的 `request` 流程。

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

### 6.2 查看和恢复（break-glass）

```bash
uv run ase project status delivery_xxx
uv run ase project resume delivery_xxx
```

每个 CLI 命令都是独立进程。`status` 从 append-only checkpoint 读取当前事实；`resume` 先对照 Git、
MySQL 和 sidecar 重算，不匹配就停止，不会覆盖现场。若返回
`VERIFICATION_APPROVAL_REQUIRED`，检查 `verification_plan_file` 后使用同一入口批准：

```bash
uv run ase project resume delivery_xxx \
  --approve-plan <full-plan-sha256> \
  --approval-reference "human-approved-candidate-verification"
```

### 6.3 检查候选变更（break-glass）

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

</details>

## 7. 数据位置与恢复责任

```text
<platform_root>/
├── team/                              # 唯一长期 Team
│   ├── team.json
│   ├── agents/ model-policies/        # AgentProfile 与模型策略
│   ├── knowledge/documents/<id>/      # 通用知识原文件、content.md、manifest
│   ├── specs/ skills/                  # Team 规范与 Skills
│   └── work-items/ leases/ metrics/   # 调度、Web Operation、租约与指标
├── projects/<project_id>/             # 与 team/ 并列；一个目录一个 Project
│   ├── project.json
│   ├── knowledge/ specs/              # Project 知识和规范
│   ├── repositories/<repository_id>/  # 代码目录绑定与 per-Repository 运行事实
│   │   └── profile/ policy/ state/ contexts/ artifacts/ evidence/ runs/ ...
│   └── requirements/<delivery_id>/    # Product/批准/方案/计划/子交付/联合验收
└── worktrees/<repository_id>/         # 当前或保留的角色隔离 checkout
```

MySQL 和整个 `platform_root` 都是恢复所需数据，应一起备份。不要只备份目标 Git 项目。干净 worktree 可
回收；dirty/漂移 worktree 会保留给人工取证。

Project/Repository/Delivery identity 都绑定唯一 Team 和所属 Project；同一源码路径登记到不同 Project
时不会共用 Repository sidecar 或 Requirement 记录。这不代替 OS 级访问控制；有宿主文件系统权限的
管理员仍能访问各目录。

## 8. Live smoke

[`scripts/smoke-live-gpt55.sh`](../scripts/smoke-live-gpt55.sh) 使用临时 Git 项目验证 Production Team
Host、配置中的模型路由、Product gate、隔离 Coder、QA 和 Reviewer。脚本文件名保留早期模型名称，
实际模型由 ASE_CONFIG 决定。它会消耗真实额度，因此默认拒绝运行：

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
- 每个 Run 都有有界调用预算；Coder checkpoint、候选复核和修复 Task 可通过统一 `resume` 接续，
  但来源/规范/权限漂移或无唯一安全现场时仍进入人工处理；
- Codex CLI 的 Coder 隔离由 Git worktree、Codex sandbox 和运行后 changed-path/commit 校验共同提供，
  不是容器级强隔离；
- HTTP Responses tool loop 只执行 allowlist 命令，但 v0.1 也不是容器级 OS sandbox；
- 不自动 merge、deploy、处理数据库迁移或跨仓库事务；
- T033 Reporter 暂停，当前用户交付是 typed JSON、candidate commit 和证据，而不是自动生成报告；
- Web Console 是可信本地单用户入口；当前无远程访问、RBAC/SSO、远程浏览器目录选择、系统开机托管或
  Keychain/Secret Service 加密凭证存储；
- PostgreSQL repository adapter 保留为后续 TODO，当前生产实现固定 MySQL 8.0。

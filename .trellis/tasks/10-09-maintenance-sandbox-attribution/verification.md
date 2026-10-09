# 验证记录：桌面维护工具 sandbox 归属

## 只读生产调查

原需求没有被重新创建，没有审批、启动 Coder、重启服务、发送进程信号或改写平台事实。

- 原任务：`task_dc5cf0aee44e5ffe0cb600557204e0d0`。
- 原调用：`run_9b76fb2865144f2abb6407923320ec4e`。
- 原工作区：`/Users/zhangjunshuai/workspace/code/.ase/worktrees/repository_c78e1680f621ff06c808aa9559666412444fbd7b/task_dc5cf0aee44e5ffe0cb600557204e0d0/coder-attempt-01`。
- 最新准备操作：`operation_1cb5e819019fd002cc58a873fc766df3`，2026-10-09 11:24:20 至 11:24:31（Asia/Shanghai），`SUCCEEDED` 操作返回 typed `WAITING / LEGACY_LOCAL_EXECUTION_ACTIVE`，没有恢复计划。
- 服务 PID `63312`，11:15:02 启动；此前修复提交 `5ca11f1` 的提交时间是 11:13:37。相关源文件修改时间早于服务启动，没有仍运行重启前服务的迹象。
- 最新 WAITING 没有封存 survey：`require_idle()` 在封存前拒绝。历史三份封存 survey 在 10:23:58、10:24:31、10:27:01 的 blockers 均为空。

实时完整扫描约 1.44 秒，固定 ps/lsof 查询全部成功。全账户文件查询发现原工作区打开文件/目录进程数为 0，最终仅 `CODEX_WRAPPER_ACTIVE`。

### 本次进程归属证据

这里的 PID 是当次 OS 事实，不能作为配置或永久豁免名单。没有打印原始 argv、配置值、环境或文件正文。

| PID | PPID | 内核程序 | 安全语义 | cwd | 原工作区打开文件 |
| --- | --- | --- | --- | --- | --- |
| 1504 | 71101 | codex | sandbox 的 Node 工具 kernel | 平台维护 checkout | 无 |
| 1505 | 71101 | codex | sandbox 的 Node trusted worker | 平台维护 checkout | 无 |
| 1513 | 1504 | node | 工具 kernel | 平台维护 checkout | 无 |
| 1514 | 1505 | node | 工具 trusted worker | 平台维护 checkout | 无 |

调查时两个 sandbox 存活约 34 分钟。完整控制链为：

```text
codex sandbox (1504/1505)
  → node_repl (71101)
  → node cua-repl.mjs (71029)
  → codex app-server (7145)
  → ChatGPT (6820)
```

`proc_pidpath` 的真实 native 路径：

- sandbox / app-server：`/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`。
- Node：`/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node`。
- REPL：`/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl`。
- App：`/Applications/ChatGPT.app/Contents/MacOS/ChatGPT`。
- 固定 REPL 脚本入口：`/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/@oai/cua-repl/bin/cua-repl.mjs`，resolve 后相同，SHA-256 为 `992174a5e637645aeb444adfdb1bae688e997bb84d7db07532f68e358e60f278`。

安全命令形态：

```text
codex [配置值省略] sandbox -- node --experimental-vm-modules <临时工具目录>/kernel.js --session-id <省略> --working-dir <平台维护 checkout>
codex [配置值省略] sandbox -- node --experimental-vm-modules <临时工具目录>/trusted-worker.js
node <固定 App bundle REPL 入口>/cua-repl.mjs
node_repl
codex [配置值省略] app-server --analytics-default-enabled [配置值省略]
```

临时工具脚本名称和目录不构成可信身份。调查中没有 `code-mode-host` 祖先；仅依赖旧的此类祖先无法覆盖当前桌面工具。

### 最小真实 OS 复现

只保留上述四个 PID 的真实 `ps` facts，针对四个 PID 做真实 `lsof`；没有 fake cwd、文件描述符或进程出生时间。查询 coverage 为 4，`path_blockers=[]`，原 scanner 仍返回 `CODEX_WRAPPER_ACTIVE`。因此这次卡点来自账户级动作判断，无法由当前维护进程实际访问原工作区的事实支持。

## 原 K1 完整性

读取整个原工作树，包括目录与 `.git` 指向文件；不跟随符号链接。每个条目绑定相对路径、完整 mode、内容长度及 SHA-256，按路径排序后用 UTF-8 canonical JSON（`ensure_ascii=False`、紧凑 separators）计算集合摘要。目录内容长度为 0；符号链接应绑定链接目标文本。Git 查询使用 `--no-optional-locks`；独立读取原 Git index 字节摘要。

| 对象 | 修复前只读基线 | 修复后只读复验 |
| --- | --- | --- |
| HEAD | `0a562f4f64ea5bbc63c371513bb623b1fe5b2101` | 相同 |
| 分支 | `ai/feature/k1-auto-knowledge-20261005` | 相同 |
| 条目 | 2,000（1,738 普通文件，262 目录，0 symlink） | 相同 |
| 完整工作树 SHA-256 | `73a2e68b582bd19ac383ec52e4791fed6fbddb3fc1a2153aed2c0383dbff5213` | 相同 |
| Git index SHA-256 | `af9cc1d7a79722081b89707083968acc89054d3767bdd084b5f046841361d293` | 相同 |
| 原工作区状态计数 | 9 个 tracked modified，15 个 untracked | 相同 |

## 新 scanner 的真实复验

源代码完成后，用真实 observer 在维护工具保持运行时只读调查同一原工作区：**第一次调查通过，`blockers=[]`**；没有失败或重试。

- 全部八个维护与控制链 PID（1504、1505、1513、1514、71101、71029、7145、6820）仍出现在真实进程清单中。
- 总调查时间 0.987 秒，版本 `local-execution-v1`。
- 首次全账户 lsof coverage 439 个 PID，路径 blockers 为空；后续 targeted lsof fresh coverage 10 个 PID，路径 blockers 为空。
- 四次固定 OS 查询均成功：ps 132,671 bytes / 0.041s；lsof 1,797,523 bytes / 0.242s；ps 132,703 bytes / 0.022s；targeted lsof 18,788 bytes / 0.012s。
- 内存中 survey SHA-256：`a54cc8a40b19a3837c4bc7d3a9756048c76d4c18e1b06e2ed34e3f011e640e0b`。没有将其写入生产 sidecar，也没有生成计划或 authority。
- 调查后的 HEAD、分支、全部 2,000 个条目、Git index SHA-256 及状态计数均和修复前完全一致，保留进度未变化。

调查通过仍不等于历史原执行停止证明，不代替用户的精确工程确认或独立 QA/Review。生产服务本轮没有被重启，只有仅读 Python 进程加载新代码做验证。

### 独立复核后最终代码见证

独立复核后，可信 App bundle 已收窄为固定 `/Applications/ChatGPT.app`，不再从 caller 或进程路径推断任意 bundle root。对这个最终语义版本进行一次必要的真实 OS 复验（2026-10-09 11:46:42.792916，Asia/Shanghai），没有轮询或重试：

- 最终 `blockers=[]`，总用时 0.951 秒。
- 同样八个维护/控制链 PID 仍在线，没有通过终止维护工具取得通过。
- 全账户 lsof coverage 441，fresh targeted coverage 9，均无原 K1 路径 blocker。
- 四次固定查询均成功，依次为 ps 133,340 bytes / 0.025s、lsof 1,796,464 bytes / 0.263s、ps 133,340 bytes / 0.023s、targeted lsof 30,374 bytes / 0.013s。
- 最终内存 survey SHA-256：`a59583eacaee01cb26e1099f7f1b6fa92dc77e5032989f7561977c7bb58d20e1`。
- 最终原 K1 HEAD、分支、2,000 条目、完整工作树 SHA-256、Git index SHA-256 及 9 modified / 15 untracked 计数均和表格的修复前基线完全相同。

上节初次见证保留用于解释此前版本的事实；本节为提交前最终代码的生产现场只读见证。没有写生产 sidecar、SQL、plan、审批或其他 ASE 事实，也没有重启服务。

## 增量检查

最终代码共236个相关增量用例通过，没有运行全量测试：

```bash
.venv/bin/pytest tests/manager/test_legacy_local_execution.py -q
```

**178 passed in 0.50s**。固定五级链、真实 OS path seam 正反例、全链自洽伪 bundle 拒绝、
祖先-only drift、两轮 coverage、原工作区 cwd/fd/声明参数、真实 exec/e 和 Linux 拒绝。

```bash
.venv/bin/pytest -q --tb=short tests/manager/test_legacy_containment.py \
  tests/contracts/test_local_legacy_rescue_schema.py \
  tests/web_console/test_legacy_rescue_acceptance.py --maxfail=1
```

**56 passed in 4.66s**。现有 containment/Schema/Console 审批、WAITING 无方案与权限边界。
两个既有 Starlette/httpx/anyio 兼容性 warning，无失败。

```bash
.venv/bin/pytest -q --tb=short tests/manager/test_legacy_rescue_delivery.py \
  -k 'False-False-True or False-True-True' --maxfail=1
```

最终代码 **2 passed, 3 deselected in 47.71s**。隔离测试 MySQL、真实 Git、native adapter 和
fake 角色输出；真实形状的双 sandbox/Node、resume/Console/idle shell 固定 OS reads 经过
完整 scanner、公开 Console/Host 方案/授权和同 Task 恢复，保留原 UNKNOWN/HEAD/index/branch，
独立 QA/Review 完整交付。反向 sandbox 打开保留文件和工具 cwd 在原 checkout 必须拒绝；
包括 binding 后 SQL consumption 前崩溃重放，无额外预算/调用副作用。无生产写入或真实模型。

Ruff check/format check 三个修改的Python文件全部通过；
`MYPYPATH=src .venv/bin/mypy --strict` 对 scanner、scanner测试、公开Host测试共3文件通过；
`git diff --check`通过。独立 reviewer 重跑scanner178用例通过，最终无blocking finding。

独立审查最初发现全链自洽伪ChatGPT.app也可放行；已改为确定性固定
`/Applications/ChatGPT.app`安装根并先red/后green验证拒绝。该来源不从进程自身数据选择。

## 存量数据处置与回滚

本次分类修复不需要改库，不重写旧 sealed survey，不改原 Task、审批、执行历史或草稿。用户在空闲时受控重启以加载最终修复，再通过原需求的“准备保留进度的恢复方案”入口重新核验。只有页面生成精确方案后，才由用户按真实停止事实确认并批准。

回滚代码必须使用受控停服/启动流程，并保留全部旧历史与工作现场；本验证没有执行回滚或服务操作。

已知范围：当前正向来源仅支持已核实的macOS固定ChatGPT安装路线；其他安装位置、桌面运行
形态、更新删除后不可读native path继续保守阻塞，不据此认定旧执行已停止。可回滚本次提交
（`git revert <本次提交SHA>`），再通过受控服务流程加载；只恢复分类逻辑，不撤销历史事实。

# 从固定发布版本运行 ASE

ASE 正在开发自己：开发检出（ai-workspace 中的仓库）同时是 ASE 的目标 Repository。若服务也从这个
可编辑检出运行，每次修平台都会让正在交付的 Task 突然换了一个引擎，冻结事实与新代码不断产生新组合。
这正是 K1 反复中断、每次都需要专用恢复路径的根因之一。

因此把两者分开：

| | 开发检出 | 运行版本 |
|---|---|---|
| 位置 | `ai-workspace/AI-software-engineering-platform` | `~/.local/share/ai-software-engineer/runtime/releases/<tag>` |
| 谁修改 | ASE 的 Coder（经 QA/Review）、平台维护者 | 从不修改；`src/` 安装后只读 |
| 用途 | 被交付的目标仓库 | 运行 `ase-console` 服务 |

运行版本是某个 tag 的独立 clone（不是开发仓库的 worktree），有自己的 `.venv`。切换版本走现有
`ase-console-service.sh restart` 的受控收尾，不绕过任何停止证明。

## 日常流程

在开发检出执行：

```bash
./scripts/ase-release.sh tag v0.1.4       # 干净 HEAD 打 tag
./scripts/ase-release.sh install v0.1.4   # clone + uv sync --frozen --no-dev，src 只读
./scripts/ase-release.sh activate v0.1.4  # 受控重启到该版本
./scripts/ase-release.sh status
```

出问题时回到上一个版本：

```bash
./scripts/ase-release.sh rollback
```

## 规则

1. 只在没有 Coder/QA/Reviewer 正在执行时 `activate`。受控重启会等待收尾；不要为了赶时间强杀进程。
2. 平台 Bug 修复先合入开发检出 main，测试通过后再 tag/install/activate。正在交付的需求继续使用它启动时的版本事实。
3. ASE 交付到开发检出的候选，由人合并；合并后是否发布新版本是单独决定。
4. 配置、日志和 `platform_root` 数据不在发布目录里，切换版本不会移动或复制它们。

首次从开发检出切换到发布版本时，`activate` 会停止当前由开发检出启动的服务，再从发布目录启动。
之后不要再从开发检出直接 `ase-console-service.sh start`。

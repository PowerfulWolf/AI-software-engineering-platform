# 发布、合并与安装记录

## ASE

- 原基线：`321f15e28e5811271d163a79ac5b7174f3b2b309`。
- 本轮修复提交：`4d1e799ed48abf0b3a8c053b71772c8567da45d2`。
- 已创建 annotated tag `v0.1.2`，精确指向该提交；`git push --atomic origin main refs/tags/v0.1.2` 成功。
- 发布前复跑 `node --test tests/team_view/*.test.cjs`：61 passed；`git diff --check` 通过。
- 其余同源码质量门见前一任务 verification.md：1971 离线 Python、最终相关 Python 151、Ruff、Mypy 485、构建与真实浏览器验证。
- 本次最终文档另行提交，tag 不移动。不创建新的生产 Requirement 或改动业务事实。

## 已交付候选的实际仓库与合并

- 仓库：`/Users/zhangjunshuai/workspace/codex/codex-quota-monitor`。
- origin：`git@github.com:PowerfulWolf/codex-quota-monitor.git`。
- 原 main/origin/main：`6d05fef305a6bcf225b526a3512c60e2679dbffe`，合并前主工作区干净。
- ASE API 确认原需求 DONE，SingleRepositoryAcceptance 与 VERIFIED 投影均绑定
  `9ac7c9ee830df548571db55ec5cf809e613467ba`，branch
  `ai/task_continue_3619e92f73a4f2794610c76cbdd24bb8/attempt-1`。
- `git merge --ff-only 9ac7c9ee830df548571db55ec5cf809e613467ba` 成功，7 文件变化，没有人工源码编辑或冲突处理。
- `git push origin main` 成功；本地和 origin/main 均为精确候选，主工作区干净。

## 构建与安装

使用已安装 `/Applications/Xcode.app/Contents/Developer`，Swift 6.4；未安装或修改工具链。

| 命令 | 结果 |
|---|---|
| `swift test` | Core 24 + App 6 = 30 XCTest，全通过；尾部 Swift Testing 0 tests 是另一 runner |
| `swift run CoreVerification` | Passed |
| `./Scripts/build-app.sh` | Release 构建成功，生成 ad-hoc 签名 App |
| `codesign --verify --deep --strict dist/CodexQuotaMonitor.app` | Passed |
| 安装后同命令检查 `/Applications/CodexQuotaMonitor.app` | Passed |

通过正常 App 退出操作关闭旧进程，确认不再运行后，将旧包移动到：
`/Users/zhangjunshuai/workspace/codex/quota-app-backup-20260928-YMoBzM/CodexQuotaMonitor.app`。
然后 `ditto` 新包到 `/Applications/CodexQuotaMonitor.app`，没有删除旧包，也没有清理 Application Support。

- 旧可执行文件 SHA-256：`0ebb5e1de190afdd1ce245a96a7ae5781ba45ce434e885c8f1e9b6fbce97ee72`。
- 新构建与安装后可执行文件 SHA-256 均为：`b6ae7d95a29e8e3582e36168822fbd51c273a5895402bbdd02b5b80c05271c62`。
- 通过系统 App 打开入口启动新包；实际进程 PID 73648，路径为安装位置，后续检查仍存活。
  这是正常无 Mock 参数的菜单栏应用启动，不是新增独立 UI verdict。
- 原生自动化读取新窗口两次超时；因此本轮只声明安装/签名/进程启动验证，未声称额外完成可见窗口交互复测。
  不影响已有 ASE 同候选独立 UI 验收记录；没有通过脚本改动用户真实账号或触发额度重置。

如需回退安装，正常退出新 App，将其另存后把上述旧包恢复到原位置。不要删除账号隔离目录、设置或历史。
Git 如需回退应创建 reviewed revert，而不是重置已发布历史。包仅用于本机，不是 Developer ID 公证分发。

## ASE 复盘与收尾

用户明确 3/4 只面向 ASE。报告已写入
`docs/archive/2026-09-28-ase-delivery-retrospective.md`，含已修根因、证据来源、角色职责和按优先级排列的未完成项。
当前路线同步到 `docs/milestones.md`；历史尚未核实的工程任务保留，不能推断已完成。
已证实完成的项目切换、联合交付恢复、14 阶段审查更新 task metadata/index；原始时间线不改写。

收尾验证：五个本轮涉及的 task.json 必需字段、唯一索引及复盘全部相对链接通过，diff check 通过。
全目录台账扫描未全通过：发现既有中文知识确认任务漏索引、通知弹窗任务缺元数据；已明确列入复盘的
历史治理项，没有把定向验证冒充全库元数据无缺陷。保留这些旧任务原文。

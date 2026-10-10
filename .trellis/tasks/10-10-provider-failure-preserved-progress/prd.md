# 保留进度后的供应方失败判定

## 目标与已复现问题

恢复首轮产生合法 coder-progress 后，下一轮在准入后调用供应方。若供应方失败且没有
改变任何现场，Codex 的失败分支仍要求 git status 为空，把之前批准保留的开发进度误归为
本轮新增修改，返回非临时 POLICY_VIOLATION；干净输入同样失败则正常返回临时供应方错误。
已用真实临时 Git 和 fake runner 复现，文件完整观察、HEAD、diff、索引和status均保持不变。

## 范围与约束

- 仅修改所列 adapter、专用测试和本任务记录；跨层规范由 root 独立同步。
- 原有精确准入/checkpoint/source/policy保持；取得准入后、模型调用前读取可信完整快照。
- 复用有界 no-follow 文件观察，包含ignored文件、正文、mode和symlink；额外观察HEAD、索引
  mode/blob/stage以及assume-unchanged、skip-worktree、intent-to-add语义。
- 比较索引语义，不比较stat时间戳或split-index内部存储标志。
- 真实中断控制仍先处理停止证明/保留/新claim；未知停止不能降为可重试供应方失败。
- 没有可信前置快照、读取不稳定或末端读取失败都fail closed。
- 不调用真实模型，不操作生产，不重置/清理任何已有工作区，不提交代码。

## 验收

1. 新建adapter接受前轮真实合法progress后，未新增修改的quota/rate/auth/timeout分别保留原分类，
   只有既有临时分类可以retry/fallback；同一Run重放不新增调用。
2. 本轮修改同一脏路径正文/mode、新增ignored文件、HEAD/索引stage/blob/flags漂移均阻止fallback。
3. 同路径内容变化不能被相同changed_paths/status隐藏；index-only变化不能被相同文件观察隐藏。
4. 正常git status刷新与split-index保存方式不改变语义快照；真实linked worktree同样生效。
5. 前/后读取失败及中断控制未知停止仍拒绝；无artifact、无candidate发布、保留原进度。

## 验证命令

先运行专用失败回归，再运行其全部测试和现有Codex/准入/供应方路由关联增量测试。
使用 `.venv/bin/python -m pytest`，指定临时 `--basetemp`，不跑全量。
执行变更文件 Ruff、format check、严格Mypy及git diff --check。

## 存量数据处置与回滚

不修改已有Task/Run/artifact/Operation或数据库。旧失败仍是旧事实，不能改判成功；已有需求须由
公开继续流程按当前完整保留进度生成新的精确恢复方案，由授权者批准后执行。部署本修复不
自动批准、重复调用或创建同名需求。回滚只撤销adapter快照判定，保留全部进度和审计记录；
旧版本可能再次误拒合法脏输入，因而应在空闲时回滚。

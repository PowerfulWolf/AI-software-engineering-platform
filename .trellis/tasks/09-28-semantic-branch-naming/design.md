# 设计草案：语义名称与执行身份分离

状态：已确认并实施。可执行契约见 `.trellis/spec/core/branch-naming.md`。

## 当前问题与证据

1. `LocalGitWorkspace._branch_name` 只有 Task ID/attempt，不能表达业务目的。
2. `CapturedChanges.to_capture` 从 Task ID 重建分支，未保存实际分支；单点改创建会破坏捕获 round-trip/digest。
3. 普通 Coder 续跑已由 coordinator 复用 attempt-1 工作树，不需要把运行轮次放进公开分支。
4. 独立 remediation/recovery 会创建新 Task 并保留旧现场；Git 不允许同一分支被两个工作树同时持有，不能把名字相同当作授权复用。

## 拟采用的契约

- 结构化表达类型（feature/bugfix）和语义短名，唯一对外形式 `ai/<type>/<slug>`。不从哈希/Task ID/重试次数拼接短名。
- 正常新需求由 Product 根据确认的业务目的提出短名，随 ProductSpec 一起展示、批准和冻结；平台以 typed contract 校验安全、长度和格式。
- Task/dispatch、WorktreeSpec、捕获/恢复、交付结果携带并校验实际名称；worktree 路径和内部 Task ID 保持原有隔离用途。
- 普通同 Task 续跑必须使用已绑定分支。独立修复/恢复需有自己的可追溯命名意图，在新计划中明确，不占用/改名旧分支。
- 同名冲突不覆盖、不自动加入随机 ID/轮次：要求更具体的业务限定词并重新绑定相关计划/批准。名称不能成为权限或 owner 的唯一凭据。
- QA/Reviewer 仍 detached，同候选 SHA、独立 Agent/Context/权限不变。

## 兼容与恢复

- 历史记录缺命名字段时按明确 legacy 格式读取，不重算历史摘要，不用新推导值改旧审批。
- 新记录的分支名称必须进入适用的 Task/计划/capture 摘要；不能仅依赖可变 Git 配置或扫描任意同前缀分支。
- 捕获 round-trip 保留真实分支；验证 Task owner、路径、common-dir、HEAD、branch/detached 状态后才恢复。
- 本任务不批量迁移生产数据，不重命名现有分支，不清理旧 worktree，不重启服务。

## 收敛决定

- 类型按原始需求性质固定；QA/Review 返工不自动改成 bugfix。
- 独立恢复使用 immediate source 名称追加 recovery；恢复计划显式保存 target_branch_name，可重新提案更具体名称并重新批准。独立验收返工与前提修复分别追加 review-fixes/prerequisite-repair。
- 类型不从旧缺字段记录猜测；旧记录保持 legacy。新 Product ready 入口严格要求名称；仅联合已批准旧文档的可信确定性投影可缺省。
- Git composition 接收 immutable Task→name 映射副本；不接受 WorktreeRef 自报分支作为所有权证明。
- 续接复核补齐干净工作树清理后的归属：语义分支名称不再含 Task ID，仅检查同名+同 SHA
  无法证明所属 Task。清理前生成绑定精确 Task/path/repository/branch/HEAD 的 manager-owned
  SHA-256 标记，恢复缺失工作树时必验。没有凭据时保留 ref 并拒绝，不补造归属；旧 Task-ID
  分支恢复兼容不变。可执行布局、哈希字段和错误矩阵见 branch-naming spec。

## 回退

尚未生成新运行记录前可回退代码；生成新格式后必须保留新字段读兼容，不能回退为只能推导旧名字的恢复器。
任何回退不删除分支、candidate、审批或 evidence。

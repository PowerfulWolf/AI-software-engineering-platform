# T044 第二阶段：不可变恢复计划与人工决定记录

## 本阶段成果

- 新增严格的 RecoveryPlan / RecoveryAuthorization 与 JSON Schema，绑定失败事实、改动快照、
  目标基线、权限及人工操作引用。不能把 hash 一致当作可信授权。
- FileRecoveryStore 在代码目录之外保存不可变记录与持久化 scope；只读打开、不覆盖既有决定，
  防范软链接、特殊文件、目录替换、跨公司读取、并发发布和不完整写入。
- RecoveryAuthorizationService 在首次批准前后复核事实；已完成请求可跨进程重放且不重复询问
  验证器。执行准入必须再次检查现场，不能直接把旧批准当作当前执行权限。
- 拒绝决定可留档但不可执行；代码中没有 Task、模型、dispatch 或 Git apply 端口。

## 验证与提交证据

- 42 项新增恢复测试，包含真实临时 Git；全量 **842 passed /81.74s**，包含专用 MySQL 测试库。
- Ruff/format（482 files）、strict Mypy（267 files）、offline lock、sdist/wheel 和 diff-check 通过。
- Schema、服务、存储及规范交叉检查通过；未改变 CLI、数据库结构或现有状态机。
- 代码基线 `6ae0608`；本记录所在提交为本阶段 feature commit，分支 `feat/t044-recovery-records`。
- 本轮真实模型调用 0；未向真实 sidecar 写入恢复批准、未编辑原需求 worktree、未推送 GitHub。
- 本机 macOS 验证；尚未在 Linux 机器实测。文件系统实现面向 macOS/Linux。

## 尚未完成与下一步

T044 保持 in_progress。下一阶段需要真实上游事实/人工操作验证器、新基线 preparation 和明确的
内容继承，然后连接新 Task/dispatch、受验证的补丁应用与生产恢复入口。最后由平台运行真实
Coder→QA→Reviewer；当前目录需求仍没有候选提交或验收结果。

双重现场检查不是跨 Git/数据库锁，调用方仍须保证旧执行器已停止。真实恢复入口不得伪造批准、
修改旧 BLOCKED 历史或绕过现有角色门禁。此次为 Astra 修复平台，不计作平台自主交付。

回滚：回退本阶段独立提交；无数据库迁移、历史记录改写或目标项目改动。

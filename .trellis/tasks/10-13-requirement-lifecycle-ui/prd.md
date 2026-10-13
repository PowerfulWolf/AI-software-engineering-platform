# 通用需求关闭、删除与资源释放

用户明确暂停 K1；本次只维护平台。关闭、删除为通用能力，删除后需求及其操作记录从日常读取消失。不提供归档。需求列表不展示项目汇总操作记录，具体过程仍在需求详情。去掉成功读取正文的冗余提示，保留真实等待与失败。上次 1b6f204 成果和本次修复经独立审查后合入 main。

## 验收
- 已删除/替换 parent 及历史 child 的 Operation 从日常列表、摘要、active/count/page 同步排除；CREATE 使用 result identity，完整不可变审计 GET/文件保留，腐坏历史仍拒绝。
- 默认需求列表没有操作记录；需求详情仍有完整操作/执行历史。成功读取没有提示空框，Product 精确正文批准门保持。
- 关闭支持空闲产品草稿、BLOCKED 及已核验停止的工程等待；活跃进程/lease 拒绝，DONE 可直接删除。
- 关闭/删除先停止历史 Task/queue，再核验并保存完整受管工作区（含 ignored/untracked 与 Git index），释放工作区，保留 branch/commit/artifact。失败保留现场和明确可重试审计。
- 资源发现绑定 Project/Repository/历史 Task/确定性基线路径；不能扫描或删除无关目录、共享数据库/源码，不能 force-remove，不能绕过 QA/Review 或恢复取消执行。
- 存量旧 K1 已正式删除且 30 工作区已释放；不重放清理。新 K1 不批准、不继续，自动化 PAUSED。

## 允许路径与验证
src/ai_software_engineer/{git,multi_directory,web_console,team_view}/、无依赖 safe_files.py、兼容重导出的 team_workspace.py 与 context/store.py 的底层安全文件依赖、tests/ 对应增量、schemas/ 新释放契约、.trellis/spec/core 与 docs/user。运行 Ruff、strict changed-file mypy、生命周期/摘要/删除测试、Node/Chrome 增量。回滚保持 CLOSE receipt 兼容读取与退休审计；新 release receipts/archives 不删除。

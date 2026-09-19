# Design

保持大部分现有路径，只为历史增加 archive 入口。docs/README.md 负责分类，archive/README.md
汇总归档，迁移表保存旧路径。projection 与静态 renderer 并入 architecture，typed tools 并入
prompt-protocol。

工程任务以原 task.json 为事实；有确切合并证据才更新 completed。缺元数据的旧记录标为
legacy_unknown 并建立索引。独立 QA/Review 原文不改，另用 evidence manifest 将旧临时路径
映射到持久文件。

不修改 AGENTS.md、工程权限规则、生产 Schema、运行时代码及平台持久事实。

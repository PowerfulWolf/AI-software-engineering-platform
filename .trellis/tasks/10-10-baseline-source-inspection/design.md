# 设计

已有 ContextVar cache 仅保存 `(source|patch, exact path, complete text)` 的不可变检测事实，
上限 512 项 / 16 MiB。嵌套 scope 复用，外层在 finally 重置；不新建缓存或解析语义。

在同步 service 生命周期及独立 store 校验边界进入该 scope。每次依然读完整原始文件、
重算所有摘要、校验全部模型/批准/历史 lineage、重新观察当前工作区和 Git。
service 返回后 Host 原有 resume/kickoff 才运行，不携带 cache 到模型执行。

性能测试通过真实公开接口和 stdlib AST 计数观察工作量；计数只作为性能契约，
不把私有缓存字段、数据库旁路查询或 scanner 自己计算的批准视为成功。

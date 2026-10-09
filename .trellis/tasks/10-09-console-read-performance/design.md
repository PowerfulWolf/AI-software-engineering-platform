# 最小安全性能闭环

## 选择

1. `source_inspection_scope() -> Iterator[None]` 使用ContextVar保存有界只读扫描结果，key为完整原文与source_path，patch另域。只缓存纯扫描事实，不缓存领域模型/审批/TeamSnapshot。每个snapshot/operation/history读取自动进入作用域，嵌套复用，finally复位。
2. `FileConsoleOperationStore.claim_next()` 在原exclusive flock内计算全部相关文件名+完整bytes的SHA256清单。只有与上次已经完整验证且无QUEUED的清单相同才返回None。清单变化重放全部模型/前驱；再次核对清单后才能保存空闲结论。list/get仍每次读取全部事实，publish使空闲结论失效。拒绝仅mtime/inode缓存，因为同大小同mtime内容篡改必须检测。
3. 同一engineering_history读取复用bindings结果，不调用两次深校验。
4. 保持40s读deadline和worker-owned Team gate；前端识别固定TEAM_READ_IN_PROGRESS机器码与abort，不解析或展示后端自由文本。忙/超时仍使用既有串行5s刷新，旧数据和输入保持。

## 边界与测试矩阵

- Good：重复完整capture扫描复用、空闲claim不重放、真实新operation马上发现。
- Base：未显式开启scope时扫描语义与旧实现相同；新进程首次claim完整验证；已有wire完全相等。
- Bad：不同text/path不能命中；secret结果不能变成安全；缓存容量触顶仅增加工作、不接受未知；损坏/新增/移除历史、symlink仍拒绝；异常后不能沿用扫描上下文。
- 不引入跨请求Team缓存、外部服务、分页wire、后台模型循环或持久化修复。真实数据验证顺序执行并注明现有服务负载，不将不同竞争环境当严格基准。

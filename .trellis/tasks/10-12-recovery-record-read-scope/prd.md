# 同步恢复核验的完整字节、只读模型复用

目标：恢复方案/审批/任务封存反复重放原始baseline/context导致分钟级CPU与分配。仅复用同一同步操作中已完整校验的immutable记录typed decoding，所有实际文件bytes/hash/路径与SQL/Git/停止/现场事实仍每次读。

范围：新read_record_scope.py、knowledge/store.py显式固定解码端口、manager/baseline_store.py Plan/Start入口、context/store.py只读Context入口，recovery/{entry,resume,current,native}.py短同步scope；专属tests/Schema不变/spec/docs/Task。禁止生产源码/服务/注册仓/SQL动作。不得缓存authority/Task/READY结论，不改变QA/Review/审批/状态机。

验收：真正baseline epochs/context resolver/service/builder重复消费者bytes每次重读、模型decode下降，旧前后SQL/capture/Git观察次数不下降；同mtime篡改/缺授权/SQL/现场漂移均拒绝；deepcopy防mutablenested污染；512entries/32MiB aggregateserialized统计，溢出完整读取，不裁历史；退出/失败/模型Run前clear，下一操作fresh。只增量tests/Ruff/strictmypy，独立审查。

存量数据处置：无SQL或journal迁移；原所有记录/Task/approval完整不变。部署等无活跃生产执行的受控窗口。回滚只撤复用scope/seam，恢复重复完整decode，保留所有事实与草稿。

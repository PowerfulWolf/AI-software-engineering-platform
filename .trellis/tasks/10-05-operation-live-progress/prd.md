# 目标与范围

同一次“继续交付”操作跨越 Designer、Planner、Coder、QA 与 Reviewer 时，操作记录仍只显示
原动作和 RUNNING。产品负责人无法知道已到计划阶段，直接根因是 renderer 未展示当前阶段。
旧父列表未 keyed，行缓存尚未执行；在本次支持历史 DOM 保留后，行签名必须包含派生进度，
否则 Requirement/Task 更新但 Operation 不变时会保留旧整行。

当前记录以当前阶段和真实节点状态为主；保留“发起操作 · 继续交付”、原命令状态和操作时间。
展示可证明的动作目的、当前原因、处理方和下一步。历史终态和其他项目/需求/非交付操作不附
最新阶段。操作标识和输入 checkpoint 摘要默认折叠，明确它是发起时版本而非最新阶段版本。

# 验收标准

- 同一完全不变的 RUNNING Operation 下 DESIGNING→PLANNING→DELIVERING 与 Coder→QA→Review
  轮询刷新当前阶段与进度；原动作、status、timestamp、hash 和 ID 不改变。
- 当前等待/审批/未知工程状态优先于命令 RUNNING，保留产品/团队/工程职责与真实下一步。
- QUEUED 仅表达等待处理；历史 SUCCEEDED/FAILED/INTERRUPTED 不套当前进度；无关 Project/
  Requirement/lifecycle/investigation 不附本需求阶段。
- 工程 IDs/hash 默认不可见，展开可核验“发起操作时的需求版本摘要”；完整历史仍无八条限制。
- 如同源通知增加当前阶段，ACTIVE key 不变，关闭后跨阶段不重弹；当前可见通知随阶段刷新。

# 允许路径与验证

见 task.json 的 scope。只运行 operation-progress/engineering-wait/product-execution/ui Node 与
execution-history/polling-state Chrome 中相关增量测试、node --check、git diff --check。

# 存量数据处置与回滚

纯前端派生，无需改库、重写历史或重新创建需求。当前正在执行的 Planner 不重启；前端资产
部署后刷新即可看到新展示。回滚前端资产并刷新，原审批和执行现场完整保留。

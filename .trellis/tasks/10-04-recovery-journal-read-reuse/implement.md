# 实现与边界

JointJournal 增加最多 512 个条目的实例缓存，每次重读路径和完整字节，只有真实内容摘要及前驱摘要相同才复用 validated typed checkpoint 与链边界。返回深复制，避免嵌套 dict 修改泄漏到缓存。缓存不能跳过旧文件读取、伪造审批或接受缺失事实。

NativeRecoverySourceReader 复用按 Project requirements root 隔离的只读 journal。NativeRecoveryEntry 的每次 inspect 保留全部 current-fact fence，复用同一个 verifier 减少跨审批/封存/执行阶段重复冷读。

存量处置：不修改原 Requirement/Task/审批/失败/工作区或 MySQL，无需迁移；现有 CLI 已加载旧代码且正在执行 Coder，不中断，不重启。新代码只在空闲时加载。目标 Coder 保持已批准 442eb51 基线。

验证限制：单次真实 K1 journal 冷读 0.798 秒、复用读 0.097 秒（同为 sequence 106）。这仅为 journal 调用测量，不表示整个恢复审批已经从 8 分钟优化到该时间；完整路径还含其他 provenance/preparation/seed 校验。

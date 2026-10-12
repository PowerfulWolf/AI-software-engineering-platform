# 设计

权威控制记录与诊断日志分离。_verified_marker 只验证已封存的小型控制事实，启动和维护完成不再读取日志；退休 _finalize 仍验证完整日志并保存真实摘要。显式 verify-retired-log 用于诊断审计，非启动前提。
本机维护CLI清理入口 purge-archived-log --confirm-delete-archived-log 固定选择当前marker引用的退休归档，在replacement lock内核验元数据和无写入者，先封存精确删除意图，再删除日志并封存ABSENT结果。重试核验同一意图/结果；未确认、篡改控制记录、symlink、非原inode等拒绝。当前服务日志不在允许路径。清理记录不审批或继续需求。
分支审计以固定main=bf3f3a8为起点；ancestor与patch-equivalence分别记录，实际缺口需验证整合。普通服务恢复与K1执行分离。

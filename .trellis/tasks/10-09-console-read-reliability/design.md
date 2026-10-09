# 设计契约

已有接口不变：GET /api/v1/team、GET /api/v1/operations。Team snapshot 纯读，事务 READ ONLY，不构造 mutation Host。

## 故障信号
真实 Team GET 两次503 TEAM_UNAVAILABLE：4.946s / 4.419s。底层 KnowledgeError RECORD_NOT_FOUND 来自处理报告 store key 校验。正确调查 proof 存在。e823e29 新增 execution_baseline_sha256=None 被非 exclude_none 的嵌套 model_dump 加入旧 key，导致真实旧记录错键。新字段使用 Field(exclude_if=None)保持旧嵌套形态；不改通用key算法，不补造调查、不宽松接受任意索引。真实非空SHA继续进入完整摘要。生产两条独立调查与frozenproof均完整。

## 验证矩阵
Good: 完整旧 report 与其合法历史 key、调查与范围均可重算，完整展示不授权新执行。
Base: 无旧记录项目、当前 key、退休计数正常。
Bad: 任意重命名、损坏摘要、错误嵌入 proof或新的未知形态拒绝，不写库。

Team 与系统分支独立发布，仍共用 serial refresh 生命周期/有界 deadline；迟到旧 Project 响应不能发布。Operations 失败仅撤销 current readiness，保留旧历史并显示读取失败。

性能：单请求已验证 history 复用；全部 bytes/integrity/schema仍验证，不使用跨请求历史cache。

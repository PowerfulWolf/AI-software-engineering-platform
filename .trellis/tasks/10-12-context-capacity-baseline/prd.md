# 原 Task 的 Coder 输入容量恢复

容量拒绝由真实 claim 发生在最终输入预检时，旧 `READY` preflight 不是工程等待
receipt，也没有 invocation。普通基线收集器无法证明这种真实 claim，不能把它改成
`WAIT_ENGINEERING`、补造调用或新建需求来绕过。

目标：公开 `propose_execution_baseline` 核验 exact final-input receipt、原完整 Context、
历史 claim/queue step、原基线和无主模型开始事实。在原 Task、Coder branch/worktree 和
工作预留上准备新执行源。公开批准强制 PAUSE，再由原公开 continue 明确 RESUME。

验收：真实隔离 MySQL 上连续一轮和两轮容量停止/基线更新后，由不同 Coder、QA、
Reviewer 完成同 candidate 的交付；Task attempt 不增加、无退款、所有原 records/events
不变、每次继续有新 Run 和 claim。缺 receipt、完整重封但异属 claim、缺 Context、
已有 invocation、孤立/损坏 native stop/receipt/admission、不可读取目录都应拒绝，
不改 Task/queue/history。所有内嵌 BaselineExecutionFacts Schema 和再生成 guards 同步。

范围不含终态 BLOCKED recovery 和 QA/Reviewer capacity resolution，分别由其他工作处理。
增量验证命令：相关 baseline/Schema/公开 MySQL tests、Ruff 和严格 mypy；不跑全量。

存量数据：不修改生产事实。仅原 Requirement 存在真实 final-input capacity receipt 的
非终态 Coder 等待可用该路径；先部署兼容版本，再准备并审批原需求精确新基线（PAUSE），
最后明确继续。旧终态没有 receipt 的 K1 必须使用独立终态核验服务，不获本路径授权。

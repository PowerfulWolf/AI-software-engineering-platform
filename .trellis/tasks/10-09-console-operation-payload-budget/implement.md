# 实施与检查计划

1. 存储回归先复现真实完整 Git plan >2 MB 持久化后不能读取，以及过预算成功写入。
2. 增加独立对称 byte budget，保留 append-only 和全部验证。
3. HTTP 回归先证明 store error 冒泡；固定安全 503 与 >2 MB list/detail 回读。
4. 工程等待、恢复入口就绪原因统一，DOM/真实浏览器覆盖读失败后无按钮说明和恢复。
5. 更新可执行 spec，记录 failure mode、存量恢复、上限和 read-only 约束。
6. 增量 pytest/Node/browser、Ruff、strict Mypy、diff check；独立审查。
7. 真实存量只读见证保留 bytes/digest，无生产写入或重启；提交推送。

验证命令与最终结果记入 verification.md；不运行全量测试。

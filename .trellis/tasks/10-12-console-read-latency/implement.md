# Implementation and verification

- 先写真实 compact→body、详情 source fence 与摘要 busy 重试回归并确认失败。
- 实现只读变化，保留错误分类与原 accepted-artifact 校验。
- 运行相关 Python/Node 增量、Ruff、严格类型检查；禁止全量 test。
- 真实只读探针比较响应内容/hash/耗时；部署用受控 restart。
- 存量数据处置：无需改库，原 K1 和保留进度不变。

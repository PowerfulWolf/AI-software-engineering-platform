# 设计

本地 CLI 进程超过调用方看门狗时，返回 typed `execution_capacity` timeout。其 `TIMEOUT` 错误码保持兼容，但不满足 provider fallback/transient refund。Responses socket timeout 与明确供应商错误仍是临时故障；没有服务端活动信号时不宣称正在思考。

联合 checkpoint 在 `attempts` 中追加 `<stage>_capacity_timeout`。一次调用前先预留工作尝试；本地触顶时追加新 checkpoint，退回该次预留、计数加一。次次启动从该计数算 `min(600 * 2**count, 2400)`。计数达到 3 则拒绝再次调用，保留原审批与产物。未知进程中断不退款。读侧预算与错误说明须识别此独立维度。

Manager 的现有生产路径只编排 typed Skills，没有结构化模型调用；若以后加入真实 Manager 模型，须再引入相同契约与持久化身份，不能复用 Product 计数。

## 验证矩阵

Good：CLI 本地触顶 600 秒，重启后 1200 秒，随后 2400 秒并成功。Base：一次有效完整产物保持原路径。Bad：504 被当容量扩容、达到上限仍调用、备用模型在本地触顶后运行、旧审批/历史被改写。

# 只读完整遍历与返回值隔离

将既有 history 内的读验循环提取为私有 _validated_history iterator。该函数每次全量枚举
并读取日志，保留既有 exact-byte/predecessor 验证缓存及 512 项上限，只 yield 内部模型。
current 必须遍历到底，保留最后一项，返回时做一次 deep copy；history 则对每项做 deep copy
并组成完整 tuple。私有 iterator 不对外暴露缓存模型，且不得提前选取最后一个文件。

测试直接封存真实 JointCheckpoint，使用实际 model_copy 的 side_effect 计数，保持真实复制
行为。完整 read_bytes 和 model_validate_json 计数分别证明 fresh reads 与原有验证复用；
历史破坏及调用方字典修改覆盖正确性边界，不使用生产数据、模型或 SQL。

已遵循 before-dev，按 core index 定位 Python/runtime、multi-directory、read-memory 与共享
thinking guides；仓库未提供 get_context.py，使用现有索引，不新增替代脚本。
root 将 executable contract 集成至 read-memory-lifecycle.md，避免跨 worker 文件冲突。

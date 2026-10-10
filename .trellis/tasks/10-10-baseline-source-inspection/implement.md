# 实现

- `ExecutionBaselineService.propose/execute/continue_execution` 的既有同步 Task lock /
  fact-fence 周期加已有 `source_inspection_scope`；未包装 Host 后续模型调用。
- `FileExecutionBaselineStore` 完整 plan/start/binding/context 校验边界进入嵌套可复用 scope。
- `FileContinuationStore` receipt get/list/put 校验和 predecessor recursion 进入同一 scope。
- 缓存仍只有有界完整文本/路径的不可变检测元组，不保存 store 文件、Pydantic model、
  Task/queue、权限、审批或 Git 观察。所有原有校验调用不变。
- 新增真实 Git / 私有文件 store 回归，先证明重复解析，再逐段包装并验证。
- 已执行 `before-dev`、`tdd`、`check`、`update-spec`；仓库没有通用 Trellis scripts，
  按已有 core indexes 和具体规范定位。该缺失不影响实现，不新增脚本。

代码与数据回滚见 PRD。独立审查已通过；未提交，等待父任务整合交付。

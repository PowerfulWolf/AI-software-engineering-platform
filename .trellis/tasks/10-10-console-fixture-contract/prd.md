# 执行展示测试对齐已提交契约

## 问题和目标

独立运行 `product-execution.test.cjs` 与 `delivery-status.test.cjs` 得到 35 项中
23 通过、12 失败；通过内存重放 HEAD 的 `app.js` 得到完全相同的失败。
11 项 fixture 直接赋值 Operations，却没有声明操作列表已成功读取；生产默认
`operationsAvailable=false` 正确拒绝从保留历史判断当前执行和审批。另一项断言要求
把当前精确审批放入折叠工程详情，与已提交的直接可见审批契约相反。

本任务只修测试，不改变生产行为、权限、阶段或持久化事实。遵循现有
`.trellis/spec/core/live-team-view.md` 的当前审批直接可见契约及
`.trellis/spec/core/incremental-polling.md` 的历史保留与 Operations 权威分离契约。

## 范围与验收标准

- 两个正常展示 harness 明确设置已成功读取 Operations；各原有阻塞、队列、claim、
  checkpoint、审批消费和跨项目断言保持，不能删除测试或放宽安全断言。
- 当前精确审批是直接可见的 section；具体方案、事实和批准入口无需打开 details。
- 补负例：同一数组保留但 Operations 读取失效时，不能冒充当前运行/已排队、
  执行准备或待批准方案；数据重新可用时恢复精确当前判断，原记录不修改。
- 不编辑 app.js、其他 agent 所拥有的历史详情测试或规范，不操作 ASE、服务或工作区。

## 验证、存量数据与回滚

只跑这两个 Node 文件、JS syntax 和 `git diff --check`；并通过只读内存重放 HEAD
证明测试对齐已提交代码，而不是依赖其他 agent 的 WIP。不跑全量，不声称视觉验收。
修复不涉及存量数据迁移；不会更新 Requirement、Task、Operation 或审批历史。
回滚仅恢复本任务两测试和任务记录，对生产无影响。

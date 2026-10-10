# 增量验证与根因

## 真实红绿与边界

初始独立执行两个未修改 Node 文件：35 项中 23 通过、12 失败。只读取得
`git show HEAD:src/ai_software_engineer/team_view/app.js` 并在 Node 进程内拦截该文件读取，
重放已提交生产资产；结果同样 23 通过、12 失败。因此失败不是另一项历史详情 WIP 引入。

根因分为两类：

- 11 项测试给 `operations` 赋值但未设置 `operationsAvailable=true`，不能把数组存在等同于
  当前读取成功。生产默认 false 和已提交 activeOperation/latestApproval 门禁保持正确。
- 1 项测试仍要求当前技术审批是关闭的工程 details，与现有规范要求精确方案直接可见相反。
  新断言验证 section、授权责任、具体标题、事实和批准按钮，不把默认折叠当成交互验收。

修改仅在 fixture 声明读取成功并对齐直接可见审批；原有 35 项完整保留。
新增 3 项分别覆盖保留 Operations 不授予上游运行/排队、原生执行准备或精确审批权威，
读取恢复后恢复当前判断；均验证原数组内容不变，任务/需求事实不伪造为运行或已批准。

## 质量门

```sh
node --test tests/team_view/product-execution.test.cjs tests/team_view/delivery-status.test.cjs
node --check tests/team_view/product-execution.test.cjs
node --check tests/team_view/delivery-status.test.cjs
git diff --check
```

- 当前工作资产：38 passed / 0 failed。
- 相同已提交 HEAD 资产内存重放：38 passed / 0 failed。
- 两文件 syntax 与 diffcheck：通过。
- `before-dev` / `check` 所引用的 `.trellis/scripts/get_context.py` 在本仓库不存在；
  已按可读的 core/index、guides/index 和相关 live-team-view/web-console/incremental-polling
  契约手动确认范围。没有报告不存在的自动规范检查已通过。
- 未跑全量，不涉及 Python 类型边界，无生产代码变更。
- fake DOM 是行为契约验证，不能替代真实浏览器视觉、焦点或移动端验收。

## 存量数据处置与回滚

测试对齐已提交契约；不修改 Schema、API 或持久化事实，无 SQL/文件历史迁移，
不操作任何 ASE 需求、审批、队列、服务或 worktree。无需为原需求做额外恢复。
回滚只还原两测试和本任务记录；生产权限和用户数据不改变。

独立审查待父任务收集。本任务不提交，由父任务在整体核验后负责提交。
# 独立审查补充

独立 reviewer 确认原 35 项用例保留，更新 fixture 和直接可见审批断言均有已提交
incremental-polling/live-team-view 契约依据；三个失效 Operations 负例没有放宽安全门禁。
独立复跑两文件 38通过/0失败，syntax 与限定 diffcheck 通过，未见阻断问题。

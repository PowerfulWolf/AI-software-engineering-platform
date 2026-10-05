# Red 证据

- 原HEAD `2c2189dad7a4b2df3ae557f4ec2a99fb0c055cd5`，新Node六条全部失败：当前行实际
  “继续交付”，缺少phase、当前等待reason/责任/下一步、Project绑定、排障输入版本标签。
- Chrome两个新回归失败，旧12条完整QA/Review/Coder历史通过。实际主标题“继续交付”，
  ACTIVE通知仍只“交付流程正在执行”；无pageerror。
- 实现live progress后的Chrome历史DOM断言揭示父ol未viewGroup；修复列表key后同一原历史行
  身份保留，当前行跨五阶段刷新。排障折叠展开也保留。

# 增量验证与独立复核（已通过）

```sh
node --test tests/team_view/operation-progress.test.cjs tests/team_view/engineering-wait.test.cjs tests/team_view/product-execution.test.cjs tests/team_view/ui.test.cjs
# 40 passed
NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules node --test tests/team_view/browser/execution-history.test.cjs tests/team_view/browser/product-execution.test.cjs tests/team_view/browser/polling-state.test.cjs
# 15 passed, 0 pageerror（history 3、product-execution 6、polling-state 6）
node --check src/ai_software_engineer/team_view/app.js
git diff --check
# passed
```

扩大检查发现旧 `Task updates retain expanded artifacts in the same modal` 用例将Task改为QA但无
有效claim，却期待“测试中”。仓库外临时目录用原HEAD app/index/style运行该exact用例仍
失败，实际“等待工程处理”；证明非本次回归。临时目录自动清理，未触碰生产。
主代理批准同步这一处stale测试契约，保留原modal/document DOM断言并新增Task status仍QA
断言；无有效claim时期待“等待工程处理”，没有修改生产状态规则来满足旧测试。

最终源码与测试增量 Node 40/40、Chrome 15/15、syntax与diff checks通过，代码冻结交独立
checker复核。未运行全量测试，没有后端/Python/Schema改动，本包为原生JavaScript无独立
TypeScript typecheck；生产截图与最终部署由主代理负责。

独立checker `node_status_check` 只读检查无剩余功能问题，独立Node 40/40，Chrome
execution-history + notifications 17/17通过；纠正PRD根因措辞：旧父列表未keyed，原缺进展
的直接原因是未渲染phase，签名缺派生facts是启用keyed列表后需同时防止的问题。
独立checker另跑polling-state Chrome 6/6通过。

# 存量数据处置与回滚

无需改库；当前Requirement/Operation/checkpoint/审批/Task facts只读使用。没有生产POST、
模型调用、服务重启、业务代码实现、commit或push。回滚前端资产并刷新即可恢复原展示。

# 增量验证记录

## Red

在修改 `app.js` 前，先改预算文案断言并加入真实 DOM 回归：

```text
NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules \
  node --test tests/team_view/browser/design-budget.test.cjs
5 passed, 2 failed
```

两处均观察到旧“下次时限”，包含 RUNNING Product 的 1200 秒窗口；失败原因与复现场景一致。
轻量测试的本地窗口断言同样 red。该文件另有既有漂移：在生产文案修改前，整详情禁止旧阻塞
文字的断言已经失败，因为完整操作历史合法保留了旧 Operation 的下一步。仅收窄为当前三个
状态/知识区域，并明确验证历史仍保留；生产历史逻辑未改。

## Green

```text
NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules \
  node --test tests/team_view/browser/design-budget.test.cjs
7 passed, 0 failed, no unhandled browser errors

node --test --test-name-pattern='local execution limit' tests/team_view/knowledge-gap.test.cjs
1 passed, 0 failed

node --test tests/team_view/knowledge-gap.test.cjs
28 passed, 0 failed

node --check src/ai_software_engineer/team_view/app.js
passed

git diff --check
passed
```

浏览器 fixture 组合 Product、Designer、Planner 与 RUNNING、FAILED 六种情况，全部显示
“当前可用执行窗口 1200 秒”。原容量耗尽、重试许可和精确设计恢复控件回归全部通过。

未运行全量测试；没有 Python/API/Schema 改动，因此无需 Python 全量类型或契约检查。

## 存量数据处置、风险与回滚

无需改数据库、journal 或任何 sealed artifact。历史 bytes/hash、Operation、checkpoint、
counter、审批及诊断保持原值。部署资产后刷新现有需求页面即可，无需重建需求或重做批准。

该展示仍是当前预算，不报告某次模型 invocation 的实际 timeout 或倒计时。回滚恢复本次前端
及文档提交并刷新页面；这项操作不改变持久化交付事实。

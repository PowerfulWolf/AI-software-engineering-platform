# 实施与验证记录

## 完成

- 增量 renderView 与源事实签名：按页面/实体跳过无关刷新，以稳定 key 在原容器内更新。
- 保留未变更的设置 form、需求/成员列表项、文档、Spec 正文、模型调用及任务详情弹窗。
- 模型诊断活动独立刷新；知识库存量列表变化参与 refresh 触发条件。
- 保留存活节点的滚动位置、文本选区和焦点；checkpoint/项目变化仍更新授权与操作闭包。
- 轻量 DOM harness 补齐新用到的标准 classList/querySelector 行为；真实 DOM 增量断言由
  Chrome 回归验证，避免仅靠 mock 断言“文字存在”。

## 增量命令与结果

```sh
NODE_PATH=/private/tmp/ase-ui-test-deps/node_modules node --test tests/team_view/browser/polling-state.test.cjs tests/team_view/browser/interactions.test.cjs tests/team_view/browser/async-boundaries.test.cjs tests/team_view/browser/settings-layout.test.cjs tests/team_view/browser/notifications.test.cjs
# 41 passed。
node --test tests/team_view/ui.test.cjs tests/team_view/readiness.test.cjs
# 42 passed。
node --check src/ai_software_engineer/team_view/app.js
git diff --check
# 通过。
```

新 polling-state 的六项覆盖：设置节点/草稿/焦点/帮助/元数据；需求详情及唯一诊断读取；
timestamp-only 的零内容 mutation、滚动/文字选区；知识资产独立更新；任务报告；旧审批失效。
两个原始症状均先验证失败再修复。未运行全量测试、Python 测试或真实模型；本次不修改 Python。

## 存量数据处置、风险与回滚

无存储、状态机、审批契约或数据迁移；刷新浏览器一次加载新脚本即可。显式页面导航、实体/
审批事实变更以及整页浏览器重新加载仍会更新相应视图。回滚本次前端提交并刷新即可恢复旧行为。
新的 UI block 必须完整声明其显示/命令依赖；不能只按 HTML 相同保留旧权限闭包。
当前目录 Python/MySQL 及 verification-environment 其他改动不属于本次提交。

# 工程等待与恢复方案分点说明

## 目标、范围与验收

两张原图对应工程等待四栏说明及调查结果、保留进度恢复方案及准备说明。保留标题和栏目，将长段落按原句顺序展示为 1、2、3 编号列表；序号与续行对齐，统一字号、行距和项间距。仅以中文句号、分号及换行分段，保留标点、原文和动态诊断，不拆英文点号、路径或错误编号；文字通过 textContent 渲染。

允许路径：`src/ai_software_engineer/team_view/{app.js,style.css}`、`.trellis/spec/core/web-console.md`、本任务目录。仅展示变更，不修改后台操作、授权、审批或持久化事实。保留其他任务未提交修改，精确提交本次差异。

## 增量验证

- `node --check src/ai_software_engineer/team_view/app.js`
- `node --test tests/team_view/engineering-wait.test.cjs`
- `NODE_PATH=/private/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/engineering-wait.test.cjs tests/team_view/browser/legacy-rescue.test.cjs`
- 隔离浏览器验证两张原图对应的列表、窄屏排版及无关轮询保持，不操作生产数据。
- `git diff --check`

## 存量与回滚

无需改库。Console 在启动时冻结前端资产，受控重启后刷新浏览器生效。回滚本任务提交、受控重启并刷新恢复旧展示。基线 `55742de`。

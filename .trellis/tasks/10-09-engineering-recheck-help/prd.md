# 工程等待复查说明角标

## 目标与范围

将“重新检查状态”的常驻说明移到按钮右上侧的可点击信息角标，按 1、2、3 点解释处理前提、点击时机及检查限制。复用现有帮助弹层；阻塞原因、处理方、具体下一步仍直接展示。仅变更前端展示，无 Schema/API 或持久化行为变化。

## 验收与允许路径

- 角标可点击、键盘打开并关闭；说明纯文本安全渲染。
- 保留服务返回的复查条件；旧执行缺失记录不能被描述为重启或重复调查即可修复。
- 按钮与角标不分离换行；窄屏无溢出，无关轮询保留已打开提示。
- 允许修改 `src/ai_software_engineer/team_view/{app.js,style.css}`、`tests/team_view/{engineering-wait.test.cjs,browser/engineering-wait.test.cjs}`、相关 `.trellis/spec/core/` 和本任务目录。
- 当前目录存在其他任务修改，只提交本任务独立差异。

## 增量验证

`node --check src/ai_software_engineer/team_view/app.js`

`node --test tests/team_view/engineering-wait.test.cjs`

`NODE_PATH=/private/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/engineering-wait.test.cjs tests/team_view/browser/legacy-rescue.test.cjs`

`git diff --check`

## 存量与回滚

无需改库，刷新浏览器加载前端。基线 `223bc94`；回滚本任务提交并刷新即可，保留其他未提交工作。

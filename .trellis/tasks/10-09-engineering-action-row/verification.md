# 工程等待操作按钮同排与本机恢复直接确认

目标：将“重新检查状态”、原角标与“复制处理报告”放到同一操作行，统一高度和间距，窄屏空间不足时自然换行。
用户追加：取消本机停止恢复方案的单独勾选框，由点击批准按钮同时确认声明和批准精确方案。声明直接可见，浏览器加载/轮询不提交确认。

范围：`src/ai_software_engineer/team_view/{app.js,style.css}`、`tests/team_view/{engineering-wait.test.cjs,browser/legacy-rescue.test.cjs}`、`.trellis/spec/core/{web-console.md,legacy-execution-rescue.md}`、`docs/user/legacy-execution-rescue.md` 和本任务目录。保留现有操作门禁及签名。基线 `66f074f`。

按本会话已读取的 Trellis before-dev / finish-work 及增量轮询规范实施；布局容器使用无事件 `viewGroup`，原按钮签名继续由 `viewBlock` 管理。

增量验证结果：

- `node --check src/ai_software_engineer/team_view/app.js` 与 `git diff --check` 通过。
- `node --test tests/team_view/engineering-wait.test.cjs`：38 项通过。
- `NODE_PATH=/private/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/engineering-wait.test.cjs`：3 项通过。
- `NODE_PATH=/private/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/legacy-rescue.test.cjs`：14 项通过，覆盖点击才确认、轮询无自动执行、未读/旧计划/能力变更后的旧按钮被拒绝。更新旧测试中的勾选操作，不执行全量测试。
- 使用隔离 legacy-rescue fixture 检查 1440/1024/390 px 的两个按钮坐标同排，查看桌面与手机截图；本机停止方案无 checkbox、批准按钮可点击、显示完整确认声明，加载新计划未提交确认。临时脚本与截图位于 `/private/tmp/ase-action-row.pG5zzr/`。
- 仅改变浏览器确认交互，继续使用原来的 `confirm_local_execution_stopped=true`、精确计划与可信工程身份；服务端校验和审计契约不变。

存量无需改库。受控重启 Console 后刷新浏览器生效；回滚本任务提交后同样受控重启并刷新。
现有待批准本机方案加载后可直接点击批准，历史决定和执行记录不重写；仅此人工点击创建本次工程确认。

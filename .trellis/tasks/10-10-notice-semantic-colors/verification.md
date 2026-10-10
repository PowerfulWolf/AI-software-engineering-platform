# 验证记录

真实Chrome fixture完全拦截http://ui.test，所有后台是只读假数据，不操作生产。
仅验证新增通知语义图标用例，不重复已通过完整通知套件。后续记录red→green与语法检查。

## Red→green

命令：

```bash
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test \
  --test-name-pattern='notification semantic colors' \
  tests/team_view/browser/notifications.test.cjs
```

- 修复前：2 failed/2.63s，两个用例均准确捕获info实际✓、预期i。
- 修复后：**2 passed/1.60s**，真实isolated Chrome，无生产流量。
- 实际QUEUED→RUNNING通知均info i，computed字色rgb(36,89,204)、背景rgb(233,239,253)。
- 关闭ACTIVE后刷新不复活；success保留绿✓，warning保留原i/黄色，error保留原!/橙色；
  普通administration提示同样info。

## 质量检查

- `node --check src/ai_software_engineer/team_view/app.js`通过。
- `node --check tests/team_view/browser/notifications.test.cjs`通过。
- `git diff --check`通过。
- 只改buildNotification两行、info CSS、追加2个浏览器case；未改signature/key/ack/control。
- 无真实模型、无生产操作、无资产热加载、未提交。root负责独立review/提交与安全空闲加载。

## 存量与回滚

无需改库，已有通知与历史从原事实重新投影。当前K1运行不受磁盘变更影响；安全空闲后加载
兼容资产并刷新页面才生效。回滚两行映射和info样式会恢复旧误绿图标，后台状态与审计保持。


独立只读review未发现实质问题；新增2项真实Chrome独立复跑通过（2.05秒），语法与diff通过。
root提交后平台有真实活动Operation，资产保持启动时冻结，不热替换或为图标重启活动执行。

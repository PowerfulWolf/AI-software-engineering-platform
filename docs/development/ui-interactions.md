# 控制台交互验证

面向修改 Console 的开发者。通知更新、表单草稿、焦点与异步导航应分别验证；
关闭通知只确认提示，不会终止后台工作或批准交付计划。

## 关键检查点

- 检查真实布局、点击命中与 computed style；仅有 `hidden=true` 不能证明遮罩已关闭。
- 轮询更新通知时保留未提交的草稿和 DOM；同一通知不重复抢焦点。
- 需求或 checkpoint 绑定变化时不复用旧表单授权；导航目标必须属于当前已验证 Project。
- Tab 留在顶层弹窗内，Escape 关闭后恢复仍有效的原焦点；辅助按钮使用 `type=button`。

## 验证矩阵

| 场景 | 断言 |
|---|---|
| 关闭通知 | computed display 为 none，无布局矩形；导航可真实点击 |
| 编辑需求时 QUEUED → FAILED | 通知更新；输入仍是同一 DOM 节点，内容保留 |
| 编辑需求时操作成功 | 通知自动移除，表单仍可编辑 |
| 未就绪提示跳转设置 | 执行设置 API 读取并显示配置表单 |
| 轮询无关 Operation | 当前通知按钮与键盘焦点保持；Product 讨论文字与截图保持 |
| Product checkpoint /执行门禁变化 | 不复用旧表单闭包、截图和提交权限 |
| 通知内 Tab / Escape | 焦点不穿透；关闭后回到原输入框 |
| 缺失/其他 Project 的需求 | 不显示不可执行的“打开需求工作区” |
| 编辑表单期间收到可跳转通知 | 先返回编辑，不提供会丢草稿或被遮挡的跳转；结束编辑后跳转恢复 |
| 系统未就绪与操作终态同时更新 | 仍协调操作事实；旧失败不能因系统提示短路而残留 |
| ACTIVE 确认后 RUNNING / 页面刷新 | 不重复通知；之后 FAILED 仍弹出一次 |
| 新重试替换旧失败 | 旧失败不再压住新状态，确认新提示后不回流 |

## 验证命令

轻量 DOM 契约仍可无依赖运行：

```sh
node --check src/ai_software_engineer/team_view/app.js
node --test tests/team_view/*.test.cjs
.venv/bin/pytest -q --tb=short tests/team_view/test_live.py
```

真实布局测试单独放在 `tests/team_view/browser/`，防止不具备浏览器的轻量环境静默跳过验证。
需有 Playwright Node 包与 Chrome；使用独立临时 profile，全量拦截 `http://ui.test/` 请求。
可复用已有安装，将其 node_modules 加入 `NODE_PATH`，也可在仓库外安装：

```sh
npm install --prefix /tmp/ase-ui-test-deps playwright
NODE_PATH=/tmp/ase-ui-test-deps/node_modules node --test tests/team_view/browser/*.test.cjs
```

有 Playwright 自带浏览器的 CI 可使用 `ASE_UI_BROWSER_CHANNEL=chromium`。浏览器启动受限时应申请
测试进程权限，不能把跳过测试当作验证通过。仅检查 DOM hidden 属性不足以证明遮罩真正关闭。


## 工程规范与历史证据

当前契约见[Web Console 规范](../../.trellis/spec/core/web-console.md)和
[Project 导航规范](../../.trellis/spec/core/project-navigation.md)。
2026-09-21 的复现、修复、执行次数与回滚记录保存在
[交互修复归档](../archive/2026-09-21-ui-notification-interactions.md)。

# 验证记录

## 红测与边界

2026-10-10，先运行专用真实 Chrome fixture 的 Team503 用例，确认在实现前因
`form.isVisible=false` 失败。缓存存在不等于用户仍可阅读或复制。浏览器使用隔离 profile，
全部 `ui.test` 请求被 fixture 拦截，没有生产写入、模型调用、审批、部署、重启或热加载。

```bash
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
node --test --test-name-pattern='Product draft remains editable through TEAM_UNAVAILABLE' \
tests/team_view/browser/product-discussion-draft.test.cjs
```

独立审查另外发现 `PRODUCT_DISCOVERY` 中断继续按钮绕过 `runUiAction`，在响应返回前的
第二次旧 click event 产生第二个 POST。专用 pending continuation 用例先确认2次POST的
红测；将此 click 纳入同一 form 的既有 `runUiAction` 后1/1通过。

## 专用 Chrome 验证

9 项通过，覆盖：

- Team busy 与 unavailable 的真实503：form/textarea/截图 DOM、文本、焦点、选区保持；
  可继续编辑、窄屏无横向溢出，旧 submit event 零截图上传/Operation POST。
- Team GET 实际 abort deadline：仅在 fixture 加速40秒定时器，旧表单保持、提交禁用，
  恢复相同事实后原草稿可提交。
- 原地 checkpoint 改变（未重绘）、新 checkpoint 重绘与 Project 切换：旧 callback
  均零写入，新作用域不能复用旧草稿。
- 第一张截图已上传，随后 checkpoint、Team 读取资格或 active Operation 改变：不上传
  第二张、不提交 Product Reply，保留原文字与两张截图并展示重新核对说明。
- 进行中 submit 与新受理 QUEUED Operation：重复旧事件不能重复上传或提交；成功请求
  精确包含原 Project/Requirement/checkpoint、文字和已上传 screenshot ID。
- `PRODUCT_DISCOVERY` 中断继续的 POST pending 与已受理 Operation：重复旧 click event
  均不产生第二个 POST，进行中按钮禁用；复用 form 级命令所有权，无新全局锁。

```bash
ASE_UI_SCREENSHOT_DIR=/tmp/ase-product-discussion-draft-20261010 \
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
node --test tests/team_view/browser/product-discussion-draft.test.cjs
```

## 相关增量回归

相关 Chrome 的 41 项全部通过，约33.86秒：

```bash
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
node --test --test-concurrency=1 \
tests/team_view/browser/interactions.test.cjs \
tests/team_view/browser/polling-state.test.cjs \
tests/team_view/browser/notifications.test.cjs
```

相关 Node 70 项通过，1 项为独立复现的既有失败：

```bash
node --test tests/team_view/ui.test.cjs \
tests/team_view/readiness.test.cjs tests/team_view/operation-progress.test.cjs
```

`ui.test.cjs` 的大型 `team, multi-directory requests, detail, refresh preservation and
stale errors` 用例在1170行先失败：QA/Reviewer队列聚合实际1项、期望2项，尚未运行后面的
讨论断言。将提交 `b2d2e68` 的 app/style/ui测试及 capability fixture 复制到隔离目录，
不含本任务改动，仍同样失败：

```bash
node --test --test-name-pattern='team, multi-directory requests' \
/var/folders/xr/6y57gfc94c77b4729m06xgjr0000gn/T/ase-product-discussion-baseline-e7vflr73/tests/team_view/ui.test.cjs
```

未为了通过此既有队列失败修改无关生产逻辑或测试。专用 Chrome 完整覆盖本任务真实 DOM
与网络写入边界。没有运行全量测试。

## 静态与视觉

JS语法与diff检查通过；无独立JS lint/typecheck配置，未改Python生产代码。

```bash
node --check src/ai_software_engineer/team_view/app.js
node --check tests/team_view/browser/product-discussion-draft.test.cjs
git diff --check
```

1440px和390px故障截图已生成并打开复核；最终版本使用简短中文，保留文本选区与截图，
提交按钮禁用，不产生多余模态通知或横向溢出：

- `/tmp/ase-product-discussion-draft-20261010/product-discussion-outage-1440.png`
- `/tmp/ase-product-discussion-draft-20261010/product-discussion-outage-390.png`

## 存量数据处置、限制与回滚

无数据库或持久化事实迁移，不审批/继续原需求，不清除工作区或历史。安全空闲维护边界
加载兼容前端资产并刷新后生效；根代理负责部署及组织规范同步。

精确 checkpoint/stage/执行门禁变化仍按既有规则失效缓存，不把旧草稿暗中提交给新事实。
已成功上传但随后控制失效的附件不代表 Product Reply 已受理，原文字/截图仍保留。回滚
本任务讨论分支与测试只恢复旧可见性，不改 Task、Operation、审批或执行现场。

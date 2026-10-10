# 增量验证

## 复现与修复

修复前运行 `node --test tests/team_view/stale-operation-notice.test.cjs`：8 条用例中 4 条失败。
红测复现了旧 PRODUCT_APPROVAL INTERRUPTED 在新 CONTINUE_DELIVERY 已完成并准备待批方案后
仍覆盖页面、关闭最新提示后旧失败回流，以及另一 Project 的同 target 操作错误压掉当前
Project 的 ACTION_REQUIRED。

修复只改 `renderOperationStatus` 通知筛选。同 Project、同非空 target 的较新操作替代旧
失败/中断/待处理即时提示，不再限定同 action；无 target 的独立管理操作仍限定同 action。
新操作可取代旧模态提示，不推断后台阻塞已经解除。原操作历史及详情真实阻塞保持。
结果含 approval 时继续由详情精确卡承载，不新增通知或授权。

## 最终定向命令与结果

```sh
node --test tests/team_view/stale-operation-notice.test.cjs \
  tests/team_view/operation-progress.test.cjs
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

结果：**23 passed**，包含 9 条新通知用例；JavaScript 语法及 whitespace 检查通过。

```sh
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
  node --test tests/team_view/browser/notifications.test.cjs
```

首次真实 Chrome 整文件 **16 passed**，约 12.7 秒。其中两条新用例验证：旧跨 action 提示
在新审批准备后被清除，详情仍显示“保留进度并继续原需求”及完整旧中断原因，连续三次
轮询不回流，导航可真实点击；当前无 approval 的 ACTION_REQUIRED 仍提示且关闭后不回旧失败。
真实 CSS 断言 `hidden=true`、computed `display=none`、零布局矩形，未发生浏览器未处理异常。

独立审查建议补充跨 action ACTIVE 的关闭回归后，新增一条浏览器用例并仅运行该增量：

```sh
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
  node --test --test-name-pattern='a running Continue replaces' \
  tests/team_view/browser/notifications.test.cjs
```

结果：**1 passed**。最终浏览器文件共 17 条，已通过上述整文件 16 条及追加 1 条增量验证；
没有为了追加用例重复运行前 16 条。使用隔离 Chrome profile，全量拦截 `http://ui.test/`
请求，没有真实生产写入、审批或服务重启。旧通知文件的既有草稿、焦点、遮罩、跳转和重试
用例均保持通过；没有运行全量测试。

## 独立审查

`/root/coder_python_tooling_fix` 只读审查通知筛选与新 Node/browser 用例，未发现实质问题。
最终独立 Node **9 passed**；隔离 Chrome 通过
`--test-name-pattern='cross-action|current recovery approval|running Continue replaces'` 对三个
新增真实交互用例独立验证，**3 passed**，约 2.66 秒；syntax/diff check 通过。
其建议的 ACTIVE 跨 action 回归已补充且验证通过。

## 存量数据处置与回滚

无需改库、不修改 Operation/Task/审批或错误历史。前端加载兼容资产后按原操作事实重算当前
提示，所有历史在原详情继续可读。没有倒填记录、隐式批准或后台继续。

回滚本次通知筛选、测试与规范后刷新前端，保持已有持久化事实；无需重启正在执行的角色。
尚未提交，本任务由主 agent 完成提交、加载及生产只读验收。

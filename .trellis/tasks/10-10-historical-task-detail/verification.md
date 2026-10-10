# 验证记录

## Red → green

`node --test tests/team_view/historical-child.test.cjs` 在实现前 3通过/5失败：历史首屏身份、
遗留 RUNNING 误报、parent/current sibling 增量上下文、parent Operation 单独变更、父导航。
修复后 8/8通过，补入阅读暂停回归后最终 9/9通过。断言实际 buildDetail、可见 DOM 和
renderDetail 的真实 keyed reconciler，未用 helper-only 断言代替目的地页面。

## 增量结果

```sh
node --test tests/team_view/historical-child.test.cjs tests/team_view/ui.test.cjs \
  tests/team_view/readiness.test.cjs tests/team_view/engineering-wait.test.cjs \
  tests/team_view/knowledge-gap.test.cjs
```

154通过/0失败。动态 dialog 名称改为 aria-labelledby 后，最后复跑直接受影响的
historical-child/ui 两文件15通过/0失败。覆盖完整13条历史、原 snapshot bytes/hash不变、
exact navigation无HTTP、parent/sibling/Operation-only更新、历史→当前、阅读暂停与stale门禁。

```sh
node --check src/ai_software_engineer/team_view/app.js
node --check tests/team_view/browser/historical-child.test.cjs
git diff --check
```

均通过。纯 JavaScript/文案展示未新增类型/API边界，没有 Python/typecheck 变化。

## 已有失败隔离

尝试受影响的 product-execution/delivery-status 两文件，共35项中12项失败。通过在 Node
进程中拦截 app.js 文件读取并注入 `git show HEAD:src/ai_software_engineer/team_view/app.js`
原文本，重放原测试仍是同样12项失败，没有写临时基线或改仓库。旧 fixture 未授权 current
Operations，以及旧审批必须折叠/旧 Manager 文案断言与已部署契约不符；本 Task 未修改它们。
root 已委派独立任务进一步确认并修正，不将既有红项报告为本次全绿。

## 浏览器限制与后续命令

浏览器历史回归新增两个真实目的地/导航/parent-only/13条历史/源hash/390、1024、1440
宽度用例；只做语法检查。依 root 指示，浏览器须通过 CUA；当前 CUA 认证不可用，不使用
外部 Playwright 绕过，因此真实视觉、点击命中、焦点和响应式布局**尚未验收**。
用户后续在已有 Playwright/Chrome 的环境可跑此单文件，不需要全量测试：

```sh
NODE_PATH=/path/to/node_modules node --test tests/team_view/browser/historical-child.test.cjs
```

## 存量数据处置、风险与回滚

不改数据库、Requirement/Task/Operation/审批或角色队列，不重写历史。加载新前端资产并刷新
原需求即可；打开原历史记录后“查看当前需求”仅导航，不审批、不恢复、不重启。
独立只读审查未发现阻断问题，独立复跑 historical-child/ui 两文件 15通过/0失败，
app/browser syntax 与限定 diffcheck 通过。真实浏览器验收限制保持。

生产 Console 在构造时冻结前端资源，不能仅刷新浏览器就加载工作区的新 JS。本次当前
K1 正在正常执行；先提交修复，待该 Operation 结束且服务排空后受控加载，再刷新原需求。
不为纯前端更新打断 Coder、不热改进程内资产、不修改旧 Requirement/Task/审批/工作区。
回滚 task.json 所列本次变更并刷新，完整旧结果、当前进度与全部批准记录保留。

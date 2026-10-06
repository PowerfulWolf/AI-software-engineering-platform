# 控制台交互验证

面向修改 Console 的开发者。通知更新、表单草稿、焦点与异步导航应分别验证；
关闭通知只确认提示，不会终止后台工作或批准交付计划。

## 关键检查点

- 检查真实布局、点击命中与 computed style；仅有 `hidden=true` 不能证明遮罩已关闭。
- 轮询更新通知时保留未提交的草稿和 DOM；同一通知不重复抢焦点。
- 需求或 checkpoint 绑定变化时不复用旧表单授权；导航目标必须属于当前已验证 Project。
- Tab 留在顶层弹窗内，Escape 关闭后恢复仍有效的原焦点；辅助按钮使用 `type=button`。
- 5 秒轮询按页面和选中实体的相关 facts 增量更新；未变化的文档、调用诊断、输入和帮助弹层
  保留原 DOM。真实浏览器断言节点身份、展开状态、草稿、滚动及选区；不能只断言文字仍存在。
  checkpoint、项目或授权事实变化时必须更新操作控件，不能以“保留交互”为由沿用旧审批。

## 验证矩阵

| 场景 | 断言 |
|---|---|
| 关闭通知 | computed display 为 none，无布局矩形；导航可真实点击 |
| 编辑需求时 QUEUED → FAILED | 通知更新；输入仍是同一 DOM 节点，内容保留 |
| 编辑需求时操作成功 | 通知自动移除，表单仍可编辑 |
| 历史需求准备上下文超限 | 通知使用中文说明实际预算问题和工程下一步；不改写原 Operation 诊断 |
| 未就绪提示跳转设置 | 执行设置 API 读取并显示配置表单 |
| 轮询无关 Operation | 当前通知按钮与键盘焦点保持；Product 讨论文字与截图保持 |
| Product checkpoint /执行门禁变化 | 不复用旧表单闭包、截图和提交权限 |
| 通知内 Tab / Escape | 焦点不穿透；关闭后回到原输入框 |
| 缺失/其他 Project 的需求 | 不显示不可执行的“打开需求工作区” |
| 编辑表单期间收到可跳转通知 | 先返回编辑，不提供会丢草稿或被遮挡的跳转；结束编辑后跳转恢复 |
| 系统未就绪与操作终态同时更新 | 仍协调操作事实；旧失败不能因系统提示短路而残留 |
| ACTIVE 确认后 RUNNING / 页面刷新 | 不重复通知；之后 FAILED 仍弹出一次 |
| 新重试替换旧失败 | 旧失败不再压住新状态，确认新提示后不回流 |
| 无关需求更新 / 当前下一步更新 | 设置表单、展开文档和已读取诊断保留；新数据可见 |
| 知识资产列表单独更新 | 列表出现新资产；已展开规范正文保留 |
| Task 更新阶段 / checkpoint 更新 | 前者保留报告；后者移除过期审批按钮 |
| 工程等待调查 / 调查缺项 | 保留 WAITING；缺项中文可见，无用户 stop bool 或恢复按钮 |
| 完整工程 proof / 精确决定 | 只提交服务 proof 和当前完整绑定；实际进度等后续执行事实 |
| 工程区展开后提交 / 轮询更新 | 展开区保持；操作控件重新绑定 checkpoint/disposition/proof |
| 多轮工程调查与处理 | 需求操作记录与任务执行历史完整可见，不截为 8 条 |
| 原分支代码基线更新 | 折叠工程区提交精确 Task/source/目标版本，默认保留草稿，封存计划后才可批准 |
| 基线保留草稿发生冲突 | 显式提出 Coder 适配完整旧补丁的新计划，不在旧批准下改变输入方式 |
| 旧基线 checkpoint / Task revision / plan | 旧控件拒提交；QA/Review 不展示 Coder 分支更新入口 |
| 原生验证准备 NOT_STARTED / FINISHED / UNCERTAIN | 只展示服务许可的不同处理方式，不把准备完成当作验收通过 |
| Task 心跳更新 / 新增历史 | 历史行、报告、模型记录保持同一 DOM；选区、展开和滚动保留 |
| Task 暂停阅读 / 异步操作完成 | 后台快照继续读取，正文保持；默认 renderDetail 不能绕过暂停 |
| Task 恢复 / Team、页面、Project 或实体变化 / 删除 | 恢复最新事实或解除暂停，不能冻结其他作用域 |
| Requirement 四章 / 混合文档名称 | 仅四个主标题，独立边框与留白；文档同级，历史有明确归属 |
| Requirement 文档选区期间轮询 | 章节父容器也 keyed，正文/选区保留；过期审批仍必须更新 |
| Task 四章 / 同级折叠项 | 仅四个主标题；报告、完整历史、模型调用和工程参考归属明确，summary 样式一致 |
| Task 长标题 / 固定工具栏 | 标题完整换行并随正文滚动；固定区域只保留关闭和阅读工具栏 |
| Task 展示状态不变 / QA → REVIEW | overview 签名包括原始 status，当前阶段仍更新 |

需求详情的四章固定为“当前进展”“产物与交付”“完整交付记录”“工程参考”。
章内只使用副标题/同级折叠项；当前操作不能放进历史或工程参考。顶部章节导航仅滚动。
Task 可点击“暂停详情更新”稳定阅读，出现新进展提示后点击“更新并恢复实时”；
此开关不暂停后台执行或 Requirement 审批事实。文档正文优先，来源/摘要放在内层折叠。
详情只有一个主要垂直滚动容器，完整历史和长报告不再在内部限高裁剪。

任务详情固定为“当前进展”“产物与报告”“完整执行记录”“工程参考”四章。
当前执行及最近 QA/Review 反馈先展示；模型调用与完整历史归入记录，身份、候选、队列和
分配归入参考。同级报告/历史/模型调用/工程折叠项的字号、边框和内边距一致，只有内层
来源元数据使用较小字号。报告实际位于 keyed `.task-artifact-list > .artifact-document`，
CSS 与浏览器断言必须覆盖该父层，不能只匹配章节直属 details。章节及报告列表由 Grid gap
提供间距，避免 margin collapse。长标题与状态不进入固定工具栏，以免遮住手机阅读区。

本次改造增量验证可使用：

```sh
node --test tests/team_view/ui.test.cjs tests/team_view/engineering-wait.test.cjs \
  tests/team_view/product-execution.test.cjs tests/team_view/operation-progress.test.cjs \
  tests/team_view/delivery-status.test.cjs tests/team_view/knowledge-gap.test.cjs
NODE_PATH=/path/to/node_modules node --test tests/team_view/browser/task-detail-reading.test.cjs \
  tests/team_view/browser/requirement-detail.test.cjs tests/team_view/browser/polling-state.test.cjs \
  tests/team_view/browser/execution-history.test.cjs tests/team_view/browser/engineering-wait.test.cjs \
  tests/team_view/browser/product-execution.test.cjs tests/team_view/browser/interactions.test.cjs \
  tests/team_view/browser/async-boundaries.test.cjs tests/team_view/browser/historical-child.test.cjs
```

存量不改库：刷新浏览器加载新资产即可；回滚资产并刷新，不改历史或审批，不需重启角色执行。

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

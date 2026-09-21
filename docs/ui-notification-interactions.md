# 控制台弹窗交互与回归（2026-09-21）

## 任务范围与验收

基线：`0b41c18`。修复 `team_view/app.js`、`style.css` 中的通知生命周期、输入命中、异步作用域、草稿与模态交互；
允许修改这些前端文件、`tests/team_view/` 和本说明。后端命令、审批、Operation 和 Task 契约不变。

验收：通知关闭或操作完成后立即恢复点击；编辑期间轮询仍更新通知；同一活动通知不重复弹出；
草稿 DOM 和输入不因通知变化重建；导航加载目标页数据；只对可验证的需求展示跳转；键盘能够关闭
通知并继续编辑。验证使用实际前端资源、模拟 API 和隔离无界面浏览器，不操作真实任务。

## 现有界面职责

| 界面 | 持续信息 | 用户动作与临时反馈 |
|---|---|---|
| 团队成员 | 当前角色、任务队列、执行事实 | 任务详情弹窗 |
| 需求与交付 | 讨论、批准、知识确认、阻塞原因与交付结果 | 新建/编辑表单、操作确认、短暂通知 |
| 知识库 | 文档、选择、规范版本、导入进度 | 导入/编辑表单与管理结果通知 |
| 设置 | 配置草稿、生效情况、待重启提示 | 保存结果、应用配置 |
| 平台状态 | 依赖与运行环境事实 | 检查结果；不自行推进交付 |

通知的“知道了”和 Escape 只确认当前提示，不终止后台工作、不批准产品/执行计划，也不解除仍然
不满足的运行条件。运行条件恢复后控件按真实 readiness 重新启用。

## 根因与交互边界

1. `#notification.modal-backdrop` 的 `display:grid` 覆盖浏览器默认的 `[hidden]` 样式。旧测试只验证
   `element.hidden === true`，没有验证真实布局。复现时关闭后的状态是 `hidden=true`、
   `display=grid`、一个布局矩形，而且 `elementFromPoint` 仍命中全屏通知层。
   隐藏元素必须强制 `display:none`；通知关闭同时移除遮罩 class 和内容。
2. 编辑表单期间跳过整页重绘保护草稿，但通知更新也跟着停止。现在每次轮询完成单独协调通知；
   打开、替换、关闭通知不调用表单重建。成功自动关闭、失败替换为终态。
3. 原先每次 render 都重建同一个通知并调用 focus，导致轮询抢走键盘焦点。相同通知内容保持节点；
   通知按稳定 key 确认，不能依赖重新计算后对象引用相等。Tab 保持在顶层通知内，Escape 关闭后
   回到仍连接的原输入控件。`render()` 重挂载原讨论表单后，只有旧控件仍连接、浏览器焦点落到
   BODY 且没有顶层弹窗时才恢复焦点，避免后台轮询中断连续打字。
4. 通知跳转原先只改 `page`，没有执行 Settings/Status 数据加载。页面导航与通知跳转复用
   `navigatePage`；需求目标必须存在于当前已验证 snapshot 且 Project 一致。有未完成表单或确认
   窗口时，通知收起所有跳转并提示先完成/取消编辑；关闭通知返回原表单。避免保留 composer 遮罩
   却宣称已进入需求工作区，也避免跳转 Settings/Status 时静默丢弃草稿。
5. 较新的重试取代同一 Project、需求和动作的旧失败提示；历史 Operation 仍保留。后台读操作和
   页面级提示不能成为新的持久化交付事实。拒绝提交和轮询产生的新通知均取代旧管理反馈，
   避免关闭后露出旧的 Project 成功提示。
6. Product 讨论表单原先在无关 Operation 刷新时也被重建，未提交文字和粘贴截图会丢失。当前按
   Project + Requirement 缓存表单，绑定 checkpoint、stage、active Operation 和 source-drift；
   同绑定复用节点与提交状态，绑定变化释放预览 URL 并重新构造，成功提交清空输入。不得跨新
   checkpoint 携带旧输入/附件授权。`systemOperationNotices()` 独立枚举当前系统条件，再按优先级
   展示；一个临时读取错误不能把仍然存在的其他问题当成已恢复。
7. 通用按钮明确使用 `type=button`；只有提交按钮使用 `type=submit`，避免表单内辅助操作隐式提交。

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

## 存量数据处置与回滚

无需改库：此次问题来自浏览器布局和内存中的通知状态，既有 Requirement、Task、Operation、审批、
知识回答与队列事实不受修改。保留正在编辑的内容后重新加载页面获取新资源；被旧遮罩挡住的需求
重新打开即可继续，后台仍在执行的任务无需再次提交。静态资源由服务按请求读取，无需为了前端
修改重启正在执行的交付服务。

回滚只恢复上述前端文件到基线版本并重新加载页面。不要回退数据库或重置 Operation；旧版本的
遮罩缺陷也会随前端回滚恢复。

## 本次执行结果

- `node --check src/ai_software_engineer/team_view/app.js`、`git diff --check` 通过。
- 轻量 UI 契约测试：37/37 通过。
- 真实 Chrome 通知与草稿回归：13/13 通过；修复前已复现遮罩拦截和 Product 草稿被清空。
- Team View Python 回归：27/27 通过，MySQL 用例使用仓库校验过的专用测试库。
- 只读检查本机控制台 8765 端口，返回的 `app.js`、`style.css` 与工作区文件 SHA-256 一致。

## 全局交互补查与修复

补查的五类问题已转成 `tests/team_view/browser/interactions.test.cjs` 中的持久回归。
修复前运行该文件，最初的 6 个真实 Chrome 测试全部失败：待提交确认仍可取消、知识串范围、
设置草稿丢失、普通弹窗 Escape 不工作、其他项目失败弹出、切换需求丢失讨论草稿。

| 问题 | 根因 | 修复后的行为 |
|---|---|---|
| 删除提交后“取消”仍可点击，旧回调清空新表单 | 异步动作没有窗口归属，关闭 UI 被误认为撤销服务端命令 | `runUiAction(owner, action)` 和 `onFormSubmit(form, action)` 绑定实际窗口/表单，等待请求结果期间禁用输入、取消和重复提交；显示“正在提交”；确认回调检查原确认对象，编辑回调检查原编辑对象 |
| 知识列表与所选范围不一致 | 全局数组在 await 后直接接收任何返回结果 | `loadKnowledge()` 捕获 scope、mode、Project 和递增请求序号；列表与索引原子发布；过期成功或失败均忽略；切换时先显示加载状态，不保留可误操作的旧列表 |
| 知识修改结果与异步正文读取落到新页面 | 动作闭包读取可变的全局 scope；修改响应直接覆盖数组 | 卡片捕获渲染时的 owner/context，写结果后仅在当前上下文重新读取；旧正文回复不能替换新编辑器；后台响应重绘保留当前 composer |
| 设置和讨论草稿在导航中丢失 | 管理页每次读取都重置草稿；讨论仅缓存一份表单 | 设置配置和 write-only 密钥草稿留在当前页面会话内存；只有无编辑时才刷新配置草稿；讨论按 Project + Requirement 保留，往返导航复用原节点；刷新/关闭页面时由浏览器提示未保存内容 |
| 普通弹窗键盘可以穿透 | 只有通知实现了 Tab/Escape | 统一顶层模态处理，背景使用 inert，Tab/Shift+Tab 留在顶层；Escape 只关闭顶层；脏表单明确确认放弃；待提交动作不允许用 Escape 冒充取消；关闭后恢复原控件焦点 |
| 其他 Project 的失败无上下文地弹出 | Operation API 是 Team 全量列表，前端未过滤 | Project 操作仅在当前已验证 Project 内提示，标题带项目名称；Team 操作标为团队；没有已验证项目时不推测目标；切到对应 Project 后可展示其未确认提示 |

### 草稿和命令边界

- 讨论缓存的 identity 是 `[project_id, requirement_id]`，提交绑定仍包含 checkpoint、stage、活动
  Operation 和 source-drift。绑定变化时释放旧截图预览并重建表单，不携带旧 checkpoint 的提交权限。
- 设置密钥草稿不进入 localStorage/sessionStorage、日志、URL 或测试输出；保存成功清空密钥草稿。
  草稿只保证当前页面会话内的导航，刷新后不会从浏览器存储恢复密钥。刷新提示不能承诺抵抗进程崩溃。
- 提交锁只覆盖浏览器等待服务端接收结果的期间；收到 QUEUED 后可正常确认提示并继续使用页面，
  后台任务不会因关闭通知而取消。失败后解除提交锁，保留原输入供重试，readiness 不可用时继续禁用交付。
- 设置保存进行中保留原表单节点和禁用状态，轮询不会生成第二份可重复保存的表单。
- 所有新操作仍通过原有后台 API；没有直接写 Task/Operation、伪造批准或修改持久化队列。

### 新增回归覆盖

除原有通知测试外，真实浏览器还覆盖：延迟删除 POST、同一范围反序响应、过期读取失败、知识类型
切换后的索引回复、启用知识后切换范围并打开新导入表单、设置密钥草稿与延迟保存、需求间导航、
普通确认/任务详情的键盘隔离、学习建议扫描返回时切换 Project、旧 Project 交付拒绝回调。所有写请求均拦截为 fixture，未对本机真实项目执行删除或保存。

### 存量数据处置

无需改库。历史 Requirement、Task、Operation、审批和知识事实保持原样；上述问题均为前端
DOM 或临时内存状态问题。恢复步骤：

1. 先另行保存当前尚未提交的文字，等待已提交请求返回结果。
2. 重新加载控制台以获取新 JS/CSS；不必重启后台服务。
3. 选择对应 Project 和需求，查看真实状态。已经 QUEUED/RUNNING 的操作继续等待，不重复提交。
4. 如之前保存设置或知识时页面卡住，先查看刷新后的服务端值，再决定是否需要重试。

回滚仍只恢复前端文件，不回退数据库，也不重置后台状态。浏览器缓存中的确认记录只是提示偏好，
不表示后台命令被撤销或批准。

## 本轮最终验证

- `node --test tests/team_view/*.test.cjs`：37/37 通过。
- `NODE_PATH=/Users/zhangjunshuai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules node --test tests/team_view/browser/notifications.test.cjs tests/team_view/browser/interactions.test.cjs tests/team_view/browser/async-boundaries.test.cjs`：28/28 通过。
- `.venv/bin/pytest -q --tb=short tests/team_view/test_live.py`：27/27 通过。
- `node --check src/ai_software_engineer/team_view/app.js`、Ruff、mypy、`git diff --check`：通过。
- 8765 只读资源校验：`app.js` 与 `style.css` 返回内容分别与工作区 SHA-256 `bd4ded4fc95b6b8b2f64a5de1b31bd598520dd2f18205a90eb4f4989cd60a46d`、`8c182749cac8f74eaaa5947ab83e8284a74fdc2695df30df1dd9baa79b8eb80d` 一致。

## 提交前补查

保留两项独立异步回归：索引重试返回时不得重建已打开的导入表单；旧 Project 的知识请求未返回时，
新 Project 的知识页面仍须独立完成加载。前者通过保留 composer DOM 修复；后者把共享管理请求
限制为 Team 设置/Project catalog 事实，知识读取始终单独绑定当前 scope，避免共享旧请求造成
新页面无限等待。两项新增测试在修复前均失败，修复后随全部 28 项浏览器测试通过。

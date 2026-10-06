# 需求详情排版与只读阻塞诊断

## 完成行为

当前名称、阶段、实际执行状态、处理方先显示；当前原因和建议操作随后显示一次。当前产品
回复/批准、待确认知识、基线处理和精确工程调查保留原 readiness/身份/权限 gate，不藏入旧讨论。
流程、仓库范围和已验证产物随后排列；旧讨论、完整操作历史、历史仓库记录、工程标识/预算及
历史知识放在后方折叠入口。全部历史保留并显示总条数，封存操作建议标为“当次下一步”。
间距/字号统一，当前操作的嵌套容器不重复分割线。移动端执行摘要单列，仓库路径和操作上下排列。
需求页在 1180px 以下切成单列，避免 1024px 窗口的侧栏与双栏最小宽度叠加造成整页横向溢出；
1024px 的真实浏览器反向测试先复现溢出，再验证修复。
外层历史折叠按 Project/Requirement 绑定，轮询保留展开、加载正文、封存行 DOM 与当前产品草稿。
无执行投影的旧待确认知识仍只显示一次，避免缓存 section 被重新移动到工程参考区。

## 验证

- `node --check src/ai_software_engineer/team_view/app.js`、`git diff --check`。
- 44 项相关 JS/DOM 检查：ui、operation-progress、historical-child、product-execution、engineering-wait。
- 相关 Chrome suites：requirement-detail、execution-history、historical-child、product-execution、
  polling-state、engineering-wait、interactions、async-boundaries、design-budget、notifications。
  历史默认折叠和预算后置后，原有 browser 测试先展开对应入口再检查正文；保留原内容/权限断言。
- 新浏览器契约检查当前原因/工程入口先于流程和历史，12 条操作完整展开、历史行与 fold 同节点，
  当前基线入口不在旧讨论中，Product 输入草稿保留，旧知识只有一个位置，渲染/展开不发 POST。
- 只读公开快照与 Operation 事实被拦截到 `http://ui.test/` 的隔离 Chrome fixture，真实 K1 的
  desktop detail 为 714px/mobile 为 352px，均无横向溢出。已逐张检查桌面及 390px 移动端截图。
  图片在平台外置维护目录 `maintenance/memory-growth-20261006/requirement-detail-{desktop,mobile}.png`。
  任何截图交互均只发生在 fixture，未点击真实平台交付按钮。

全部 59 项相关 Chrome 检查已有通过结果。首轮 57 项通过，2 项旧预算断言因预算后置折叠需要
适配；关闭 fixture 操作通知并展开工程详情后，重跑 design-budget 和 requirement-detail
得到 10/10 通过。没有改动预算算法、移除断言或放宽动作 gate。

```sh
node --check src/ai_software_engineer/team_view/app.js
node --test tests/team_view/ui.test.cjs tests/team_view/operation-progress.test.cjs tests/team_view/historical-child.test.cjs tests/team_view/product-execution.test.cjs tests/team_view/engineering-wait.test.cjs
NODE_PATH=/Users/zhangjunshuai/workspace/code/.ase/maintenance/ui-test-tools/node_modules node --test tests/team_view/browser/requirement-detail.test.cjs tests/team_view/browser/execution-history.test.cjs tests/team_view/browser/historical-child.test.cjs tests/team_view/browser/product-execution.test.cjs tests/team_view/browser/polling-state.test.cjs tests/team_view/browser/engineering-wait.test.cjs tests/team_view/browser/interactions.test.cjs tests/team_view/browser/async-boundaries.test.cjs tests/team_view/browser/design-budget.test.cjs tests/team_view/browser/notifications.test.cjs
NODE_PATH=/Users/zhangjunshuai/workspace/code/.ase/maintenance/ui-test-tools/node_modules node --test tests/team_view/browser/design-budget.test.cjs tests/team_view/browser/requirement-detail.test.cjs
git diff --check
```

仅运行增量检查；Chrome 工具依赖存于外置维护目录，不进入生产依赖或目标仓库。

独立只读 reviewer `/root/delivery_patch_check` 复核代码/规范/任务及真实浏览器路径，无问题。
其额外 `knowledge-gap.test.cjs` 31/31、requirement-detail/design-budget 10/10，通过；
1024px 补充修复后又独立复跑 requirement-detail 3/3，无问题。root 对补充 CSS 的
requirement-detail/polling-state 9/9、UI 6/6，通过。没有运行全项目测试。

## 当前和历史 K1 原因

原父需求仍为 `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`。
当前验证快照是父 checkpoint 第 34 条：DELIVERING；Task
`task_dc5cf0aee44e5ffe0cb600557204e0d0` 保存 IMPLEMENTING、实际 WAITING，Coder 为
WAITING_DEPENDENCY/ENVIRONMENT_UNAVAILABLE，无候选代码。这是模型调用前的工程前提等待。
10 月 6 日 00:19:48（北京时间）的 SHA 校验通过 preflight receipt 记载受控验证能力发现不可用，
但没有保存具体缺少哪个前提。不能猜测 Docker、MySQL或模型服务是哪一项当时失败。

历史 `delivery_197e43958545579951b26746f2d837f3` 在 DESIGNING/INVALID_AGENT_OUTPUT
停止，无 Task/业务候选代码。`ac_010_002` 声明 integration 却只有 source inspection；
`ac_011_003` 声明 security 却只有 document inspection。原生拒绝正确；旧联合 Design 的
校验时机和英文泛化摘要有问题。同一父需求第 26 条进入修正，第 28 条发布修正 Design，
后来重新计划和交付；新设计已经提供两项精确 pytest 入口。此历史错误不阻塞当前工作项。

独立只读宿主检查确认 Codex、Docker、Colima Unix socket、daemon、缓存 mysql:8.0 镜像和
官方 `discover_python_mysql_host_prerequisites` 当前 READY；公开配置的 Codex 路径一致。
这不自动取消原工作项旧等待，也不替代本工作项的正式调查 proof。未运行测试/容器/SQL或读取密钥。

用户操作路径：需求列表打开原 K1 → 工程授权者展开“工程处理 · 调查与决定” → “调查工程等待”。
若没有缺失事实且平台给出“确认前提并继续”，用户再执行该项；若仍有缺项，处理后点击
“重新调查工程等待”。实际按钮按当前 proof 的 permitted resolution 显示，不能承诺现在即可恢复。
沿现有需求和 Task 继续。当前没有新的调查 proof，本任务没有执行上述调查、决定、批准或继续。

## 存量数据处置与回滚

无需 SQL/journal/Task/Operation/批准或证据迁移。所有事实保持原值；布局修复通过前端资产更新
和浏览器刷新生效。回滚前端资产后刷新即可恢复旧展示，不改交付检查点。诊断缺少具体前提是
已确认的现有可观测性限制，本任务不补造旧证据或用只读宿主检查冒充工作项工程调查。

# 同代码版本容量恢复前端验证

工作树：`/Users/zhangjunshuai/workspace/code/ase-same-source-capacity`。
起点：`0c1053540beb214e0b4839a28906909c80957353`；提交前按后端作者协调快进至 `54ed9fe`。
本记录仅说明前端子任务的增量验证与独立审查，不代表后端或生产已经发布。

## 可独立审查的文件

- `src/ai_software_engineer/team_view/app.js`
- `tests/team_view/context-capacity-resume.test.cjs`
- `tests/team_view/browser/context-capacity-resume.test.cjs`
- `docs/user/team-console.md`
- `.trellis/tasks/10-12-same-base-capacity-resume/frontend-design.md`
- 本文件

同树中的 `tests/manager/test_same_base_capacity_baseline.py`、主任务文档和 task.json
由后端子任务拥有，不在此前端提交范围。

## 契约回归结果

新测试在实现前实际运行过：原始 7 条中 1 PASS、6 FAIL。
实现后补充 Project/岗位/等待身份、混合证明拒绝、无完整记录不宣称 no-start、
完整 binding/summary/待执行计划用途和独立 RESUME 等反向检查，最终新增文件 9 PASS。

最终增量命令：

```sh
node --test tests/team_view/engineering-wait.test.cjs \
  tests/team_view/stopped-provider-retry.test.cjs \
  tests/team_view/operation-summary-reading.test.cjs \
  tests/team_view/context-capacity-resume.test.cjs
```

结果：**159 PASS，0 FAIL，0 SKIP**，约 0.42 秒。复用既有工程等待、恢复审批、提供方失败、
代码与规范更新、完整 Operation 读取的门禁用例；没有运行全量测试。

## 真实浏览器增量结果

复用仓库现有浏览器 fixture，Chrome 使用独立临时 profile，所有 `http://ui.test/` 请求完全拦截。
没有调用生产 ASE、模型、真实项目恢复或审批。复用仓库外已有 Playwright 包，无新增运行依赖。

```sh
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
  node --test tests/team_view/browser/context-capacity-resume.test.cjs
```

结果：**4 PASS，0 FAIL，0 SKIP**，最终运行约 7.24 秒：

1. 原需求容量卡片直接可见；target-free PROPOSE 完整精确绑定；无可见版本输入或停止/提供方确认。
2. Task 无关心跳更新后标题、说明和批准按钮保持同一 DOM；焦点、选区与展开核对信息保留。
   在 390/1440 两种宽度实际检查按钮边界并截图。
3. plan、receipt 或 v8 能力变化后旧批准节点脱离 DOM；旧节点 click 不产生 POST。
4. exact EXECUTE 只提交 PAUSE；模拟服务持久化暂停后才出现单独继续；RESUME 精确引用原绑定和处置摘要。

浏览器初次运行因新增 fixture 未提供 typed result 的 Project/Requirement 身份，出现 1 PASS/3 FAIL。
已补充合法 fixture 身份并重跑至上述全绿，没有放宽生产 result scope 校验。

两张最终布局图在仓库外 `/tmp/ase-context-capacity-ui-20261012/ready-390.png`
和 `ready-1440.png`。已查看两个宽度的真实渲染：操作可见、文字自然换行、核对信息折叠归属明确，
技术摘要长行在手机宽度内换行。截图中的选区来自用于验证阅读稳定性的真实文本选区。

## 静态与跨层检查

`node --check src/ai_software_engineer/team_view/app.js` 和 `git diff --check` 通过。
前端无独立 lint/typecheck 配置；不以与改动无关的 Python 检查代替 JavaScript 语法及交互契约验证。

按 `check`、`check-cross-layer` 复核适用的核心 Web Console/live-team-view、
execution-baseline/baseline-context-projection 和 UI interaction 规范：

- 读取：可信 WAITING facts/receipt → 当前精确计划 → 可见决定；缺失、不匹配与旧服务均拒绝。
- 写入：点击重验 → 既有 submitOperation 及完整读取/控制资格重验 → 三个既有 typed 动作。
- 复用：沿用 baseline exact identity、pause、resume、deliveryButton、操作进展、keyed DOM，
  未建立另一套恢复状态机或审批权限。
- 一致性：同代码版本用途在卡片和操作记录中保持，不误称更新代码；带容量 binding 的 RESUME
  仍使用既有继续动作。独立 `source_rebind` 的代码/规范审批语义保持。
- 待后端落实：v8 能力、target-free PROPOSE、新用途全链路校验，以及摘要从 binding 补充 purpose。
  这些尚未发布，不能仅凭本 UI 增量宣称原 Task 可以恢复。

## 存量数据处置、风险与回滚

没有改库、重写历史或隐式继续现有需求。现有容量等待在新后端通过完整事实核验后，
仍由原需求的“准备方案 → 精确批准保持暂停 → 单独继续”追加新事实。
完整事实不足时保留原现场，不把 unknown 改为 PASS。当前生产 K1 的代码基线更新路线
不依赖此前端功能，本子任务不参与其紧急发布。

v8 前端必须与后端契约一起审查发布。旧服务会显示能力不可用，已有 v7 代码更新入口继续可用。
回滚前端只撤回可见新能力并刷新资产，不发送额外命令；保留已写的新用途历史与后台可读兼容，
不将容量用途伪装为 source_rebind，不自动补做批准或继续。

## 独立审查

独立审查者 `/root/summary_result_scope_compat` 完整阅读上述 6 文件、设计与用户说明后给出 PASS，
无阻断发现。审查者独立复跑 4 个 Node 文件 **159 PASS / 0 FAIL**，约 0.49 秒；
独立复跑真实 Chrome 增量 **4 PASS / 0 FAIL**，约 7.77 秒；3 个 JS 语法和 diff 检查均通过。
审查者实际查看了两个宽度截图，并检查异步完整 Operation 重读期间 contract/capability
仍由 `operationWriteOwnerSignature` fence。UI 可独立提交；必须等后端 v8 与 binding purpose 摘要
补点完成后配套集成发布，不参与紧急知识 claim 修复发布。

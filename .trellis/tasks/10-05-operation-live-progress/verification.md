# Red 证据

- 原HEAD `2c2189dad7a4b2df3ae557f4ec2a99fb0c055cd5`，新Node六条全部失败：当前行实际
  “继续交付”，缺少phase、当前等待reason/责任/下一步、Project绑定、排障输入版本标签。
- Chrome两个新回归失败，旧12条完整QA/Review/Coder历史通过。实际主标题“继续交付”，
  ACTIVE通知仍只“交付流程正在执行”；无pageerror。
- 实现live progress后的Chrome历史DOM断言揭示父ol未viewGroup；修复列表key后同一原历史行
  身份保留，当前行跨五阶段刷新。排障折叠展开也保留。

# 增量验证与独立复核（已通过）

```sh
node --test tests/team_view/operation-progress.test.cjs tests/team_view/engineering-wait.test.cjs tests/team_view/product-execution.test.cjs tests/team_view/ui.test.cjs
# 40 passed
NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules node --test tests/team_view/browser/execution-history.test.cjs tests/team_view/browser/product-execution.test.cjs tests/team_view/browser/polling-state.test.cjs
# 15 passed, 0 pageerror（history 3、product-execution 6、polling-state 6）
node --check src/ai_software_engineer/team_view/app.js
git diff --check
# passed
```

扩大检查发现旧 `Task updates retain expanded artifacts in the same modal` 用例将Task改为QA但无
有效claim，却期待“测试中”。仓库外临时目录用原HEAD app/index/style运行该exact用例仍
失败，实际“等待工程处理”；证明非本次回归。临时目录自动清理，未触碰生产。
主代理批准同步这一处stale测试契约，保留原modal/document DOM断言并新增Task status仍QA
断言；无有效claim时期待“等待工程处理”，没有修改生产状态规则来满足旧测试。

最终源码与测试增量 Node 40/40、Chrome 15/15、syntax与diff checks通过，代码冻结交独立
checker复核。未运行全量测试，没有后端/Python/Schema改动，本包为原生JavaScript无独立
TypeScript typecheck；生产截图与最终部署由主代理负责。

独立checker `node_status_check` 只读检查无剩余功能问题，独立Node 40/40，Chrome
execution-history + notifications 17/17通过；纠正PRD根因措辞：旧父列表未keyed，原缺进展
的直接原因是未渲染phase，签名缺派生facts是启用keyed列表后需同时防止的问题。
独立checker另跑polling-state Chrome 6/6通过。

# 生产续验追加：命令成功与当次交付结果分开

主代理生产只读验证发现原同一Operation于13:38:56结束，命令SUCCEEDED但封存result.stage
是BLOCKED（设计到计划交接未通过校验）。追加red：两条Node及一条真实Chrome在原`aae0b1a`资产上
失败，历史行仅“继续交付 · 执行成功”，未展示原result.stage与diagnostic。

追加recordedOperationOutcome，从封存result.stage显示当次阻塞/等待/已交付；只有DONE
表示当次需求已交付，CLOSED/中间阶段/未知/无结果不推断完成。SUCCEEDED产品状态标为
“命令已完成”，原始SUCCEEDED留排障。Req后来DONE也保留旧BLOCKED标题与当次原因。
Designer固定missing planning handoff精确中文映射，原英文诊断及用户引用保持。

```sh
node --test tests/team_view/operation-progress.test.cjs tests/team_view/engineering-wait.test.cjs tests/team_view/product-execution.test.cjs tests/team_view/ui.test.cjs
# 42 passed
NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules node --test tests/team_view/browser/execution-history.test.cjs tests/team_view/browser/notifications.test.cjs
# 18 passed, 0 pageerror
node --check src/ai_software_engineer/team_view/app.js
git diff --check
# passed
```

末轮补充中间阶段/CLOSED/未知阶段与原型键名不误报交付完成的Node负向断言后再次42/42
通过，Chrome exact sealed outcome回归再次通过。只改只读显示；原计划交接流程bug由主代理
另建任务诊断，未改Python/Schema/持久状态或重启服务。

独立checker `node_status_check` 对最终冻结diff复核确认只读取封存result.stage/diagnostic，
hasOwn和负向用例齐全，未发现剩余问题；独立Chrome history+notifications 18/18通过。

# 最后窄修：完成命令中性色与校验失败语义

完成命令之前仍继承badge.current蓝色。沿原sealed用例补red断言：Node和Chrome都精确
失败于“badge current”不等于“badge”。当前结果已有error类但原CSS没有通用.error定义，
因此增加唯一局部selector `.execution-history-entry > strong.error` 使阻塞主标题为红色。
SUCCEEDED记录badge局部清除current，灰色静态；全局badge与原始status保持，不染绿色。

固定missing handoff中文改为“设计到计划的交接尚未通过校验，当前交付已阻塞。由工程团队
核验具体原因并处理。”，兼容native交接转换拒绝与未发布情况，不推断实体文件丢失。

只跑原sealed两个Node及一个Chrome增量用例：2/2与1/1通过；Chrome断言command badge
无current，computed color/background为中性灰，BLOCKED标题computed color为红色。
syntax/diff checks通过，没有扩大测试范围、修改Python、生产写入或重启。

# 存量数据处置与回滚

最终局部样式与中文补丁由 delivery_patch_check 独立复核：sealed Node 两例、真实 Chrome
sealed outcome 一例、JS语法与前端路径 diff 检查全部通过，无剩余问题。SUCCEEDED 命令徽标
静态灰，BLOCKED 当次交付标题 computed color 为红；不推断交接文件丢失。

无需改库；当前Requirement/Operation/checkpoint/审批/Task facts只读使用。没有生产POST、
模型调用、服务重启、业务代码实现、commit或push。回滚前端资产并刷新即可恢复原展示。

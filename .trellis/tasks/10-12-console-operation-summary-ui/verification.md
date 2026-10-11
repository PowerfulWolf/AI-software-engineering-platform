# 增量验证

## 红绿与真实页面

最初5项新增测试在原 `1769977` 全红，缺摘要读协议函数。完成实现后新18项全绿，
含当前审批fresh读取正例、digest/selection/active/scope反例、分页、Team同ID隔离与
实际UTF-8/count cache逐出不得READY。只运行以下7个相关Node文件：**224 passed**。

```sh
node --test tests/team_view/operation-summary-reading.test.cjs tests/team_view/readiness.test.cjs tests/team_view/engineering-wait.test.cjs tests/team_view/operation-progress.test.cjs tests/team_view/operation-capabilities.test.cjs tests/team_view/stale-operation-notice.test.cjs tests/team_view/ui.test.cjs
```

真实Chrome测试与既有polling-state：**13 passed**，全部使用 `http://ui.test` fake routes，
不访问生产ASE。新的4项验证首次完整方案、后续304不取完整list、61条历史三页全部可达、
页外单条处理原因完整读取、关闭释放对象、点击审批时digest变化零POST，和历史详情GET
pending时关闭后late completed响应仍释放完整cache、不把内容重新写入关闭区块。

```sh
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test tests/team_view/browser/operation-summary-reading.test.cjs tests/team_view/browser/polling-state.test.cjs
```

真实页面发现并补齐两类fake测试遗漏：初始空历史placeholder必须在首次scope读取后填充；
分页变化必须进入incremental render签名，否则点击后数据改变但DOM不更新。
`node --check app.js` 和 `git diff --check` 通过；此任务仅JavaScript与Markdown，
Python Ruff/mypy不适用。没有运行全量测试。

## 独立审查与修复

Root检查cache/分页后补core spec index；独立Agent `native_truncated_diagnosis`审授权边界，
发现empty sources（新建需求）在fresh 304期间跨Team或manifest降级时可能发POST。
实际submitOperation与late200反例先红，修复专用read owner generation、snapshot/Console
Team、Project/selection和能力manifest签名；每await检查，304重验prior exactscope/cache
实例，实际POST前再次对比原owner。正常刷新不改变owner generation；latefullcallback
不缓存也不撤销新owner控制。独立Agent终复审通过，18项新增Node复跑通过，crossTeam/
capability实际zeroPOST、正常create正例1POST；checkpoint/fullplan digest/active-operation
原门独立probe仍zeroPOST。

历史pending-close真实Chrome反例先红后绿。最终日志：
`/tmp/ase-summary-ui-final-all-node.log`（224）、
`/tmp/ase-summary-ui-final-all-chrome.log`（13）。没有验证生产HTTP/审批执行。

## 结果和限制

摘要响应独立于完整Operation；完整cache 8条/32MiB并禁止缺来源READY；旧服务保留兼容。
旧审批/plan读取消费者仍使用真实full records，共享写入口fresh摘要/单条fullGET后比较
完整request/currentTask/source/selection/project，不自动选择新审批内容。
历史显式分页当前页+最近4页可回退，返回最新可重新走到任意旧页，避免留存全量模型。
第一次当前scope定位需只读遍历summary页，之后同inventory轮询不复读完整详情；
极端当前匹配完整来源>8条或>32MiB时明确不可用，不伪造READY，需平台拆分展示入口。
本轮验证没有对生产CPU/RSS做上线后测量，不宣称内存泄漏已根除或K1已交付。

## 存量数据处置

**无需改库/改写Operation。** 原完整历史、精确审批、Task、失败与执行证据、工作区不变。
此任务仅独立worktree实施，主仓/注册仓及生产服务均未改。部署需等真实执行和Operation
空闲后受控重启，加载同版本backend和frontend，再刷新原K1详情。

## 回滚

空闲受控维护时revert前端提交，保留后端旧GET兼容和全部完整Operation；不用删历史、
重建Requirement、补造批准或改动生产SQL。后台summarycache是只读，不改变stockfacts。

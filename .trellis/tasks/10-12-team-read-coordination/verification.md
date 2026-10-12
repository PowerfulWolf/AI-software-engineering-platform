# 增量验证与存量处置

2026-10-12 基于9825b8b，独立worktree task/team-read-coordination；不操作生产、SQL、服务或模型。

## 真实RED

新增Node真实refresh调用链首轮3FAIL，91.95ms：summary持有时detail仍发GET（1!=0）；detail
持有时summary仍发GET（1!=0）；固定外部busy被记为error而非有限waiting。先写测试再实现。
实现中额外readiness2FAIL定位已有queuedProject预期；保留原读取和latest publication契约修正
后通过，不弱化原断言。新Chrome首轮6PASS/1FAIL，8.92s，仅新增fixture误读h.state.reads，已
改为保存独立readPaths引用；该结果不是平台bug或跳过。

## 最终命令与结果

```sh
node --test tests/team_view/team-summary-reading.test.cjs tests/team_view/readiness.test.cjs \
  tests/team_view/operation-summary-reading.test.cjs tests/team_view/ui.test.cjs
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test \
  tests/team_view/browser/team-summary-reading.test.cjs \
  tests/team_view/browser/polling-scheduler.test.cjs \
  tests/team_view/browser/detail-read-freshness.test.cjs
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

Node **111PASS，0.441s**；真实Chrome **15PASS，10.318s**；syntax/diff通过。未运行全量测试。
项目此静态JS资产没有ESLint、TypeScript或pnpm package/typecheck配置；未声称Python Mypy能
验证JS。Node执行真实资产、Chrome执行真实DOM/请求/时钟作为对应增量质量门。

覆盖摘要/详情双向serialGET且辅助Operation独立、完整body解析、20轮取消等待Set归零、
summary先发布后只发新locator、固定busy三次boundedtimer/耗尽manualretry、busy后真实
不可用/409/非法body立即停止、关闭移除timer、Product批准在waiting/error时禁用、原完整
14+返工历史、选区/DOM/滚动以及原五秒poll与10/20/30秒summary退避。

独立review待完成。本测试都通过offline fixtures拦截；没有拿browserabort证明serverworker
停止，也没有把重复busy采样断言为同一读取持有数分钟。

独立review发现P2：summary未传current，排在held detail后的旧Project仍先发旧GET。新增
真实coordinatedReads回归先RED（1FAIL，84.58ms），实际URLs为current,next而期望只有next；
补summary的`current: () => !superseded()`后增量summary-reading+readiness **80PASS，0.260s**。
已有readiness两条专测“已进入的旧Project读”现在先await并断言原GET确已进入，再导航；
原失败/成功、B→C/latest、旧数据不能重标、辅助ready断言全部保留，没有弱化该契约。
新回归则证明“尚排队的旧GET”被跳过、browser abort后仍held的HTTP不提前退役、最终仅新
Project GET且read owner/waiters/refresh均释放。当前等待P2修复的独立复审，尚未提交。

P2修复后仅重新执行最近Chrome `browser/team-summary-reading.test.cjs` 与
`browser/polling-scheduler.test.cjs`，**10PASS，9.107s**；syntax/diff继续通过。未重跑此前已通过
且本次未改的其余Chrome文件或全量测试。

## 存量数据处置

不改数据库或已封存事实：本次只修浏览器请求竞争和错误展示。现有Requirement、Task、
Operation、精确审批、QA/Review历史和开发进度无需迁移；加载兼容资产并刷新浏览器即可。
后端singleworker及实际worker-owned释放保持原样。真实TEAM_UNAVAILABLE仍需独立调查，
本修复不会将其改为成功或重新运行交付。回滚前端提交并刷新即可。

## 最终独立审查

两个独立reviewer最终PASS。原P2 Project切换旧GET问题已修；同一真实harness复验只发project_next，waiters/flight/refresh owner全释放。独立Node80PASS/0.307s；不重复已通过Chrome，不操作生产。

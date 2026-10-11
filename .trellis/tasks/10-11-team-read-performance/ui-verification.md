# UI 调度修复与增量验证

## 实现范围

仅在隔离 checkout `/Users/zhangjunshuai/workspace/code/ase-team-read-performance` 开发，未改主 checkout、生产资产或 K1 开发现场。UI 改动位于 `src/ai_software_engineer/team_view/app.js`：

- 保留原 `refreshFlight`/latest-intent串行流；完整刷新结束后才安排唯一的五秒自动 Team timer。手动刷新和 Project 导航移除旧 timer，立即受理；当前读结束后仍立即 drain 最后目标。
- 当前 Team busy/timeout使自动等待按10→20→30秒增加，上限30秒；成功Team与普通unavailable回到五秒。辅助Operations/Knowledge失败不会把已发布Team误判为繁忙。
- 恢复准备明细仍使用独立五秒interval/self single flight，interval不再顺带读取Team。40秒观察截止与服务器worker-owned互斥保持。
- 连接文案改为“读取完成后自动更新，繁忙时稍后重试”。普通Task“最近活动”改为“最近交付记录”，历史“当次记录更新”保留；不改变last_activity、排序或心跳来源。旧数据提示、当前控制门禁、正文DOM、草稿、焦点与精确授权不变。
- 同步 `.trellis/spec/core/project-navigation.md` 与 `incremental-polling.md` 的签名、调度规则、错误矩阵与验证要求。

测试基建明确区分Team timer与相同5000ms的配置提示过期timer。readiness假timer可指定callback；原显式UI tick不再依赖准备interval；其他Chrome fixture关闭自动Team回调，保留真实deadline/普通UI timer。新的scheduler浏览器用例启用真实setTimeout并使用Chrome受控时钟，验证实际GET。

## Red → Green 与命令

先新增四个调度契约回归，在原版执行：

```sh
node --test --test-name-pattern='automatic Team|timed out Team observation|successful Team data does not back off' tests/team_view/readiness.test.cjs
```

结果：4/4失败，均因原版没有完成后自动timer/退避。实现后运行：

```sh
node --test tests/team_view/readiness.test.cjs tests/team_view/knowledge-gap.test.cjs tests/team_view/ui.test.cjs
node --test tests/team_view/preparation-progress.test.cjs
node --test --test-name-pattern='consecutive Team deadlines|validated Team facts publish' tests/team_view/readiness.test.cjs
```

结果：首组97通过、独立准备10通过；随后新增连续deadline上限回归及强化辅助读取完成前零timer断言，最后2项通过（其中1项重复验证）。该阶段合计108个不同DOM用例通过。

```sh
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test \
  tests/team_view/browser/polling-scheduler.test.cjs \
  tests/team_view/browser/polling-state.test.cjs \
  tests/team_view/browser/preparation-progress.test.cjs \
  tests/team_view/browser/detail-read-freshness.test.cjs \
  tests/team_view/browser/recovery-read-contention.test.cjs
```

结果：22项真实Chrome用例全部通过。新增scheduler3项：8秒慢读取完成后再等5秒；连续busy10/20/30上限、成功回5秒并保留同一草稿DOM；真实preparation GET在Team held期间仍每5秒执行。

```sh
node --check src/ai_software_engineer/team_view/app.js
node --check tests/team_view/browser/fixture.cjs
node --check tests/team_view/browser/polling-scheduler.test.cjs
git diff --check
```

全部通过。本仓UI为原生JavaScript，无pnpm/TypeScript构建配置；没有运行全量Python或全量浏览器测试。`.trellis/scripts/get_context.py`在此仓不存在，已按before-dev手工读取core/guides索引、架构、contracts与相关UI/生命周期规范。

## 当前生产响应的隔离只读回放

Root已保存的脱敏Team wire `/tmp/ase-k1-team-20261011-1720.json`，观察时间为2026-10-11 09:20:40 UTC。本次只在隔离Chrome中用本地资产回放；所有HTTP拦截，非GET拒绝，无真实ASE或外网访问，无永久production fixture。

结果：K1需求和Task均显示“实现 · 执行中 / Coder正在执行”；实现节点蓝色 `rgb(36,89,204)`，Product/Design/Plan绿色；未来QA/Review未被当作执行中。旧历史未覆盖当前状态，Task显示独立最近心跳。实际写请求0，外部请求0。截图已目视确认：

- `/tmp/ase-team-ui-readonly-replay-request-20261011.png`
- `/tmp/ase-team-ui-readonly-replay-task-20261011.png`

回放仅证明所提供观察时间的展示，不宣称当前实时服务状态或后续交付结果。

## 独立复核、存量与回滚

`inspect_recovery_entry`只读复核UI核心未发现阻断；指出“只有合法Team发布才恢复五秒”的排他措辞与unavailable规则矛盾，已修正文档。Root另行集成后端与任务说明。

存量数据处置：UI没有Schema/API/SQL/journal或持久化审批变更，不改需求、Task、Operation、工作区或真实执行。空闲受控维护边界加载兼容资产后刷新原页面即可。回滚UI资产与相应spec/test恢复旧频率，所有真实交付事实保留。性能优化不能保证多标签页永不遇到busy；全局互斥继续保护内存，首次完整历史读取仍有实际成本。


## 截图核验后的精准文案修复

实际回放同时展示交付记录15:30:36与当前执行心跳17:20:32。只读核对确认普通Task
`last_activity=max(child checkpoint.checkpointed_at, task.updated_at)`不包含进行中的主调用或
queue心跳；“最近活动”用词偏宽。经Root明确授权，仅把普通Task文案改“最近交付记录”，
历史“当次记录更新”保留，后端时间计算/排序/状态推断均不改。

新增现有readiness DOM seam断言：旧last_activity和新heartbeat同时存在，交付时间与独立
最近心跳各自展示，Coder仍执行中，原last_activity字节保持。改文案前此用例红灯；改后
针对该用例运行通过。最终共109个不同DOM用例与22个Chrome用例通过。

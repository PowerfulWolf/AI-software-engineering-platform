# 需求与任务详情改造验证

## 问题与实现

旧 Task 详情的历史列表/行和模型调用缺少完整 keyed 父子容器，心跳变化会重建内容。
只读浏览器调查观察到 QA 文字选区在轮询后消失，原历史行/文本节点断开；
外层弹窗、限高历史和限高报告还产生多层滚动。已改为增量保留完整记录与正文。
Task 增加暂停详情更新/恢复，后台快照仍继续更新，暂停不承载任何批准操作。

需求详情原先最多 13 个平铺模块，h2、文档 summary、历史 summary 和工程 summary
混在同一层。现固定四章：当前进展、产物与交付、完整交付记录、工程参考。
章节有独立编号/边框/背景/留白，章内副标题与文档折叠项层级一致。
所有当前知识事项（包括 Team/Engineering）仍在当前章；参考只保存历史知识。

独立审查发现并修复：默认 renderDetail 的异步回调曾绕过暂停；无活动时的空执行卡；
当前工程知识审批误放参考。真实截图发现并修复：不同历史类型外观不一致；
移动端不滚动的 overflow 祖先使章节导航无法 sticky。上述边界已纳入回归。

## 增量验证

以下命令在最终前端版本通过，未运行全量测试。Playwright/Chrome 复用仓库外已有依赖。

```sh
node --check src/ai_software_engineer/team_view/app.js
git diff --check
node --test tests/team_view/ui.test.cjs tests/team_view/engineering-wait.test.cjs \
  tests/team_view/product-execution.test.cjs tests/team_view/operation-progress.test.cjs \
  tests/team_view/delivery-status.test.cjs tests/team_view/knowledge-gap.test.cjs
NODE_PATH=/path/to/node_modules node --test tests/team_view/browser/task-detail-reading.test.cjs \
  tests/team_view/browser/requirement-detail.test.cjs tests/team_view/browser/polling-state.test.cjs \
  tests/team_view/browser/execution-history.test.cjs tests/team_view/browser/engineering-wait.test.cjs \
  tests/team_view/browser/product-execution.test.cjs tests/team_view/browser/interactions.test.cjs \
  tests/team_view/browser/async-boundaries.test.cjs tests/team_view/browser/historical-child.test.cjs
```

- 轻量 JS 契约：91 项通过，0 失败。
- 真实 Chrome：43 项通过，0 失败；全部 API 请求由隔离 fixture 拦截。
- 独立 reviewer 对 Task 阅读和 Requirement 章节分别审查并运行针对性 Chrome 检查，无遗留发现。
- 心跳/追加历史保留选区、原 DOM、滚动、报告/记录展开；完整历史超过 8 条仍全部保留。
- 暂停后 snapshot 已更新而正文不变；默认 render 回调也不覆盖，显式恢复读取最新事实。
- Team/page/Project/实体变化与 Task 消失解除暂停；Requirement 旧 checkpoint 审批不复用。
- 当前产品回复、工程等待/基线操作和当前知识均保持原作用域与门禁；不因排版产生非 GET 请求。
- 390/1024/1440 px 真实布局截图检查：章节边界/同级文档一致、无横溢出、正文末尾可读；
  导航目标标题不被 sticky 导航遮住，Task sticky 顶栏和手机 fixed 弹窗保持正确。
- 只读 GET localhost:8765/app.js 与 style.css 为 200，字节摘要与工作区一致、no-store；
  当前运行服务已经提供新资产，刷新浏览器即可。

## 存量数据处置

无需修改持久化数据：本次仅前端展示和读状态改造，没有 API/Schema/数据库变更。
原 Requirement、Task、Operation、历史、候选提交与审批仍由已有校验后的事实提供。
没有代用户调查、审批、恢复、继续交付、更新基线或新建需求；没有读取凭证文件。
现有需求加载新前端后继续按当前章的原操作入口由用户处理。

## 已知范围与回滚

完整展示服务已提供的正文；仅有身份引用而未提供正文的文档仍明确说明正文尚未接入。
完整浏览器刷新会开启新视图，阅读暂停不是持久化设置，也不暂停后台 Agent。
回滚本次 app.js/style.css 并刷新页面即可恢复原展示；不修改历史、不重启正在运行的角色，
无需数据库回滚。前端变更没有新的仓库依赖或生成模板需要同步。

## 标题右侧状态跟进

按用户两张截图，将 Requirement 和 Task 的状态都移至标题右侧同一行。
原标题/状态 facts 保持不变，标题可换行、状态不压缩；Requirement 新父容器也保持 keyed。
独立复核同时发现徽章签名遗漏交付阶段：同一个 RUNNING 状态跨 DESIGNING/PLANNING
曾保留旧阶段。签名现包括 deliveryPhase，并在既有跨阶段浏览器用例增加徽章同步断言。
仅跑上述相关浏览器文件；另用隔离 Chrome fixture 检查两类标题在 1440/390 px、普通/长标题
共 8 种布局，状态均在右侧且无溢出。存量处理和回滚方式与本任务一致。

## 抬头整体性跟进

按用户后续截图，将需求详情的上下两行收进同一个有边界的抬头卡片。
上行“需求详情”和管理控件统一 13px 紧凑字号，关闭按钮采用次级样式；
下行标题与状态相邻，标题不再占满剩余宽度。任务标题也采用相邻状态保持一致。
原事实、签名、key 和操作闭包不变；管理按钮的 primary/danger 颜色保留。

现有 Requirement/Task 浏览器增量共 8 项通过。另在隔离 Chrome fixture 检查
两类标题 × 1440/390px × 普通/长标题共 8 种布局，状态紧邻且无溢出；
computed fontSize 证明需求详情/关闭详情字号一致，primary/danger 颜色未被关闭样式覆盖。
桌面和手机抬头截图已目视检查，独立 reviewer 局部复核未发现未解决问题。
仅前端展示，无数据迁移，存量和回滚方式与前述相同。

## Task 四章跟进

按用户任务详情截图，将 Task 也重排为四章：当前进展、产物与报告、完整执行记录、工程参考。
当前执行说明和最近 QA/Review 反馈放在第一章；全部报告放在第二章；完整历史及已完成模型
调用放在第三章；任务身份、候选版本、角色队列和分配放在第四章。同级折叠项统一字号、
边框和内边距，章节和报告列表使用 Grid gap，避免相邻卡片的 margin collapse。

Task 长标题与状态放在随正文滚动的抬头，固定区域只保留任务详情、关闭和阅读工具栏。
只有四章使用 h2，内部标题降为 h3；所有新增章节及列表父容器仍为 keyed viewGroup。
另补入 overview 的原始 item.status 签名：展示 WAITING/RUNNING 不变时，交付阶段仍可能从
QA 进入 REVIEW，不能保留旧阶段。文档样式覆盖实际的 task-artifact-list 父层。

本轮只跑相关增量检查：

```sh
node --test tests/team_view/ui.test.cjs tests/team_view/product-execution.test.cjs \
  tests/team_view/delivery-status.test.cjs
NODE_PATH=/path/to/node_modules node --test tests/team_view/browser/task-detail-reading.test.cjs \
  tests/team_view/browser/requirement-detail.test.cjs tests/team_view/browser/polling-state.test.cjs \
  tests/team_view/browser/execution-history.test.cjs tests/team_view/browser/historical-child.test.cjs \
  tests/team_view/browser/product-execution.test.cjs tests/team_view/browser/interactions.test.cjs
```

- 轻量 JS 契约 41 项通过；隔离 Chrome 36 项通过，全部请求由 fixture 拦截。
- 独立 reviewer 发现工程折叠样式断言的 selector 漏项；按反馈修复后，Task reading 单独重跑
  4 项全部通过，工程参考也纳入同级样式检查。
- 390/1024/1440 px 无横向溢出，长标题完整且不占固定顶部，长报告末尾可读。
- QA → REVIEW 时显示阶段更新；阅读选区、原 DOM、滚动、展开及暂停/恢复边界继续通过。
- 独立复核确认 Task 保持只读，没有新增业务操作，也没有改变 Requirement 的审批门禁。
- 只读 GET 127.0.0.1:8765/app.js 与 style.css 均为 200、no-store，字节摘要与本轮工作区一致。
- 截图底部重复片段经像素比较及 CDP 交叉截图确认为本机 Chrome headless 截图尺寸问题，
  非重复 DOM 或 UI 卡片；原生 surface 截图与 DOM 命中交叉验证正常，没有为截图管线改动 CSS。

存量数据处置：无需改库或迁移，Task 和 Requirement 的原历史、报告与审批事实保持原契约。
刷新浏览器加载前端资产即可；回滚本轮 app.js/style.css 并刷新，不需数据库回滚或重启角色。

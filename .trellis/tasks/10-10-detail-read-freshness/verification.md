# 验证记录

## 范围与结论

2026-10-10，只运行增量验证。新增隔离 Chrome 回归 5/5 通过，相关 Node 回归 65/65
通过。相关 Chrome 文件 17 项通过、1 项为独立复现的既有失败，见下文。所有浏览器 HTTP
均使用 fixture；未调用生产模型、批准或继续需求、写入生产事实、重启服务或加载生产资产。

## 先红后绿

- RUNNING Requirement 回归在实现前因详情没有就近读取提示而失败。
- BLOCKED 回归先补齐 fixture 的显式详情选择，再确认其失败原因同样是缺少读取提示。
- 实现后 5 个独立 Chrome 测试全部通过；最终一次约 14.16 秒。

```bash
ASE_UI_SCREENSHOT_DIR=/tmp/ase-detail-read-freshness-20261010 \
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
node --test tests/team_view/browser/detail-read-freshness.test.cjs
```

实际覆盖：

1. 有效 Coder claim 下的 RUNNING Requirement 遇 Team 503，仍保留“实现 · 执行中”原事实，
   同时展示原 snapshot 时间与读取失败说明；恢复后提示消失，控制恢复。
2. BLOCKED Requirement 保留阻塞事实，读取失败时旧审批 callback 不能产生 POST；恢复只
   恢复匹配当前事实的审批入口，新 checkpoint 不复活旧审批。保留现有控制资格计算行为：
   读取失败时“待工程确认”标签会因控制资格不可用显示为“已阻塞 · 已阻塞”。
3. 暂停阅读的 Task 在后台接纳较新 snapshot 后仍显示原正文的来源时间，原标题/正文
   DOM 不变；恢复不自行解除暂停，用户恢复阅读后才切换到新内容。
4. Project 切换后绑定新实体与新时间，不能串用旧 Project 来源。
5. 打开的 Requirement composer 草稿节点和值在读取故障及恢复期间保持，零写请求。

展开文档、正文/overview DOM、文本选择保持。插入提示会触发浏览器滚动锚定，因此验证
正文相对自身滚动容器的位置误差不超过 8px，不要求 scrollTop 数值完全不变。布局测量和
截图前等待两次 requestAnimationFrame。1440px 和 390px 无横向溢出，390px 暂停 Task
粘性标题区高度小于 260px。

## 相关回归

以下 65 项全部通过，约 0.40 秒：

```bash
node --test tests/team_view/readiness.test.cjs tests/team_view/operation-progress.test.cjs
```

以下相关 Chrome 文件 17 项通过、1 项失败，约 27.06 秒：

```bash
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
node --test --test-concurrency=1 \
tests/team_view/browser/task-detail-reading.test.cjs \
tests/team_view/browser/polling-state.test.cjs \
tests/team_view/browser/requirement-detail.test.cjs \
tests/team_view/browser/recovery-read-contention.test.cjs
```

既有失败为 `task-detail-reading.test.cjs` 中的
`Task hierarchy and long reports fit narrow screens with one scrolling reading surface`：
fixture 被归为历史任务，实际章节是“当次执行结果”，测试期待“当前进展”。将提交
`3b77839` 的干净 app/style 资产与原测试复制到隔离目录，未包含本任务改动，仍出现相同
失败；本任务未修改该测试或其章节分类。

```bash
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules \
node --test --test-name-pattern='Task hierarchy and long reports' \
/var/folders/xr/6y57gfc94c77b4729m06xgjr0000gn/T/ase-detail-read-freshness-baseline-uhks7z4f/task-detail-reading.test.cjs
```

## 语法与视觉复核

以下检查全部通过；当前仓库没有独立 JS lint/typecheck 配置。本任务没有 Python 生产改动。

```bash
node --check src/ai_software_engineer/team_view/app.js
node --check tests/team_view/browser/detail-read-freshness.test.cjs
git diff --check
```

最终截图已打开复核：桌面提示紧邻需求标题、文字紧凑；窄屏 Task 提示位于阅读工具栏下，
正文可读且没有重复标题或横向溢出。

- `/tmp/ase-detail-read-freshness-20261010/detail-read-freshness-running-1440.png`
- `/tmp/ase-detail-read-freshness-20261010/detail-read-freshness-running-390.png`
- `/tmp/ase-detail-read-freshness-20261010/detail-read-freshness-paused-task-390.png`

## 存量数据处置与回滚

不涉及数据库、Schema、Operation、审批、队列或执行事实迁移；旧 Requirement、Task 和
工作区无需改写。仅在安全空闲边界加载兼容资产后刷新浏览器即可生效；部署由主代理负责。
回滚 app/style 和本任务浏览器测试即可移除就近读取提示，持久化现场和历史保持不变。

Product 讨论草稿在读取故障期间暂不可见属于独立既有交互缺口，已在 `followups.md`
记录精确复现与建议边界，未声明本任务已修复；按主代理安排暂不开始后续实现。

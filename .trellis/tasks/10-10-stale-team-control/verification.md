# 验证记录

## 先红后绿

- `node --test --test-name-pattern='stale Team|failed Team branch' tests/team_view/readiness.test.cjs tests/team_view/engineering-wait.test.cjs`
  修复前 5 failed：独立辅助读取正常时旧 Team 可控制、旧中断按钮提交、辅助仍挂起时未撤权；
  修复后 5 passed。工程旧 callback 矩阵覆盖 3 种失败 × 5 种当前决定。
- `node --test --test-name-pattern='stale Team pauses knowledge|retained knowledge approval|knowledge approval rechecks' tests/team_view/knowledge-gap.test.cjs`
  修复前 3 failed：stale form POST、错误 Project POST、hash await 后错误 POST；修复后 3 passed。
  后续扩展到 9 种 exact binding 变化及 hash await 中 Team/checkpoint/已批准变化，均拒绝 POST。
- 新增真实 `reconcileViewChildren` 文档/source 保留测试与 Team 成功后辅助失败测试，定向 10 passed。

## 自动检查

- `node --test --test-reporter=dot tests/team_view/readiness.test.cjs tests/team_view/engineering-wait.test.cjs tests/team_view/knowledge-gap.test.cjs`
  → **139 passed，0 failed**，约 0.19 秒（仅 3 个受影响文件）。
- `node --check src/ai_software_engineer/team_view/app.js` → passed。
- `git diff --check` → passed。
- 独立只读 reviewer 运行 9 条重点 selector、syntax/diffcheck 并审查最终 diff，结果通过，
  未见剩余实现阻断；规范中的缓存绑定表述修正为 exact gap ID，callback 另核验 full gap signature。

只运行相关 Node 文件，无全量测试。
fake HTTP/DOM/hashing harness 无真实 POST，不代表实际浏览器视觉、焦点或移动端布局已验收。

## 存量数据处置与回滚

读侧变更，不需要改库、迁移审批或重写旧 Operation。原需求加载兼容新 assets 后刷新，
读取恢复会重新核对 exact 决定，刷新自身不会批准或启动 Coder。
回滚本任务 JS/spec/test 变更并刷新页面；所有旧历史、现场和角色验收证据保持。

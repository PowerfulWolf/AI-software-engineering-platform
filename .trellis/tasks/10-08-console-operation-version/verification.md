# 验证与存量数据处置

## 原因与复现

- 只读检查：8765 监听进程的启动时间为 2026-10-06；新 HANDLE 修复提交 `8b31c96` 时间为 2026-10-08。
- GET `/api/v1/console` 返回旧运行契约，没有 `supported_actions`；GET `/app.js` 已包含新 HANDLE 控件。
- 隔离读取 `8b31c96^` transport/models，与当前磁盘 UI 配对，完整合法 HANDLE 返回
  `422 INVALID_REQUEST / Operation input is invalid.`，`console.submit` 调用 0 次。
- 同 envelope 经当前 HEAD 的真实 TestClient 返回 202。原错误是新页面与旧运行模型混搭，
  不代表 Manager 审批失败或原需求新增阻塞。

## 增量验证

- 后台红回归：`pytest tests/web_console/test_transport.py -q -k
  'operation_manifest or static_assets_remain or http_handle_wait or http_unknown_action'`：
  修复前 4 failed / 1 passed；修复后 5 passed。
- `.venv/bin/python -m pytest tests/web_console/test_transport.py -q`：25 passed，2 条既有依赖 deprecation。
  真实 HTTP 使用完整合法 HANDLE、FileConsoleOperationStore reopen、精确重放、拒绝外部 stop flag，
  同时区分 schema 输入错误与 `console.submit` 内部记录 ValidationError。
- UI 操作契约红回归最初 4 failed；最终 capability CJS 7 passed；受影响 CJS 119 passed：
  `node --test tests/team_view/operation-capabilities.test.cjs tests/team_view/engineering-wait.test.cjs
  tests/team_view/readiness.test.cjs tests/team_view/ui.test.cjs
  tests/team_view/product-execution.test.cjs tests/team_view/knowledge-gap.test.cjs`。
- 浏览器操作契约、工程等待与 polling 增量：11 passed，全部隔离 fixture，无生产写入。
  使用现有 runtime 的 `NODE_PATH`，执行 `node --test
  tests/team_view/browser/operation-capabilities.test.cjs
  tests/team_view/browser/engineering-wait.test.cjs tests/team_view/browser/polling-state.test.cjs`。
- Ruff format/check、Mypy transport、`node --check`、`git diff --check` 通过。
- 遵照用户约束，未跑全量测试；未重启服务、审批/恢复/继续真实需求或修改生产数据库。
- 最终措辞回归保持已受理 RUNNING 操作、RESOLVED 决定和既有 handling 建议，能力变化只影响
  后续新请求。未点击的页面提示不声称请求被拒绝，真正 guard/旧 422 才标记本次未受理。

## 存量数据处置

无需数据库迁移。本次 422 在输入校验阶段拒绝，没有受理 Operation，也没有启动 Manager 或改变
审批、工作区、Run、Task、重试预算。用户等当前操作与角色执行自然结束，在服务空闲时运行：

```sh
./scripts/ase-console-service.sh restart
```

刷新后回到原需求，再点击“让平台处理中断”。新服务能受理 HANDLE；原第 6 轮是否可恢复仍以
原停止/claim/现场及冻结授权校验为准，本修复不伪造缺失事实、不重建需求或放宽授权。

## 风险与回滚

静态 UI 现在随服务启动固定，部署任何 UI 更新也需空闲加载新服务；页面仍保持 no-store 响应。
manifest 是兼容性声明，不授予权限或代替审批。回滚前空闲停止服务，撤本轮提交后再启动和刷新，
保留所有 Task、草稿、审批与 immutable 审计历史。本轮没有替用户验收真实交付。

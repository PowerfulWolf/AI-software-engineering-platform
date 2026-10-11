# Console 和公开交付链路验证

## 结果

- DOM 增量：`node --test tests/team_view/stopped-provider-retry.test.cjs tests/team_view/engineering-wait.test.cjs`，104 passed。
- 真实 Chrome：`NODE_PATH=/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/stopped-provider-retry.test.cjs`，2 passed。
- 公开 Host/MySQL：`PYTHONPATH=src python -m pytest -q tests/manager/test_production_execution_baseline.py -k public_stopped_provider`，2 passed，117.85s。
- 旧 completed-output 同基线公开链路：同文件 `-k completed_output_same_base_pause_resume`，1 passed，47.38s。
- Console 能力 manifest：`tests/web_console/test_transport.py -k operation_manifest`，1 passed。
- Root 所有变更 Python Ruff/format 和 Console 两源文件 strict mypy 通过。

公开链路使用隔离测试 MySQL、fake 模型与测试拥有的真实子进程，非生产数据库或真实业务执行。
覆盖永久 AUTH 原结果、真实 failed/非零停止、原 stop 错误 AUTH、完整现场、原 Task/分支、
同基线和显式新基线、精确人工 PAUSE、单独 RESUME、普通工作额度、新 Run/claim，最终
由不同 Agent 完成同一候选的 QA PASS 和 Review APPROVE。审批后崩溃、SQL release 后
崩溃、工作区和暂存区漂移均拒绝或精确重放，没有重复审批/工作预留。

浏览器覆盖 390px 和 1440px 关键内容、无关轮询保留 checkbox 与 focus、精确计划变化
重置确认、旧 detached 控件零 POST。DOM 覆盖同源恢复和 source-rebind 联合确认、
不匹配失败/stop/Project/source/checkpoint/plan/能力拒绝，以及当前事实优先、历史调查保留。

独立前端复审识别并修复了真实 wire 缺省字段问题：公开 `to_wire()` 会递归省略
None，因此无 artifact 的 FAILED 结果通常不含 artifact 键。provider 与既有 completed
恢复入口现在都接受缺省或 null，拒绝真实 artifact；两个 fixture 默认使用真实 wire
形态，并补兼容反例，避免页面有成功方案却没有可用按钮。

## 真实存量只读核对

K1 原 Task `task_recovery_8ca06fa0aec236ab940597ad1482bfc8` 的第 9 轮
`run_1d9f8fa7cbd94a368f715967f103ee28`：原 outcome FAILED AUTH、非临时、无 artifact；
真实 capture stop failed/returncode1/output_absent、无 cause，original_error_code=AUTH。
原 start/outcome/claim/work/source/checkpoint 身份一致。新 proof 构造校验通过；原调用
开始到本次核对的完整 inventory 无变化（包括零新增非缓存路径）。没有改 SQL、改旧
outcome、补停止证明、退款或操作生产恢复。准备/执行时仍需服务重新核验鲜活停止事实。

原调用 raw stderr 没有保留，仅有摘要，因此不能证明背景 MCP 日志污染就是历史首因。
另一个分类任务只修复之后调用的主错误选择，不重标原认证失败。

## 存量数据处置与回滚

空闲时受控加载兼容版本，同一原需求通过公开入口 PROPOSE；若更新平台源码，则使用
显式 SOURCE_REBIND 并完整审阅项目原生规范差异。精确确认提供方前提已检查/修复、
批准 PAUSE，独立核对完整现场后再显式 RESUME。保留原失败、旧未知结果、Task、分支
和审批历史，不新建同名需求。此文的 fixture 通过不等于 K1 已交付。

新增 proof/binding 保存后只能回滚到可读取该附加契约的版本；不删除记录或现场，不
把旧授权用于新工作。不执行自动 merge。当前只跑增量验证，全量仍由用户选择执行。

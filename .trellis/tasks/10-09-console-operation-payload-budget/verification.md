# 验证与存量处置

2026-10-09 13:48（北京时间）已在用户明确授权后完成旧故障实例的一次维护升级，
并由独立只读验收确认原方案可完整读取、工作区与业务事实未变。下面的“未操作生产”描述
保留修复提交时的历史事实；部署结果与用户下一步见 [维护记录](maintenance.md)。

## 根因见证

当前原需求仍是 Task `task_dc5cf0aee44e5ffe0cb600557204e0d0` / Run
`run_9b76fb2865144f2abb6407923320ec4e`，Task IMPLEMENTING，attempt 6 的 WorkItem
WAITING_DEPENDENCY / EXECUTION_UNCERTAIN。恢复准备操作
`operation_dac65f2d0a4deb7914377f995fe2caa1` 于北京时间 12:32:34 已封存
SUCCEEDED / sequence 3 / typed legacy rescue READY。完整结果记录 2,177,461 bytes，
旧读取限制 256,000 bytes，使 list/detail HTTP500。浏览器清空 Operations、失去control门禁，
所以无法呈现已准备方案与审批按钮。这不是再次出现进程误判。

真实服务仍是 PID1797，启动12:31:03，日志在本次启动后记录
`Console dispatcher stopped before safe finalization`；原 `claim_next()` 读取上述大记录失败
会保存内存 sticky shutdown failure。磁盘代码更新不会解除旧实例的拒绝，也不能承诺普通
restart/resume能让该实例退出。本轮未向服务发送任何信号或生产写请求。

## Red → green

- Store新回归最初2项失败：>2MB完整Git计划写后无法重读，以及escaping使超预算仍被写入。
- HTTP固定读取错误回归最初冒出store异常；修复后conflict/validation/I/O/budget list/detail
  8项全部为安全503，Console metadata保持真实readiness。
- UI读取失败原先无常驻说明；同时team/operations失败又暴露旧勾选审批在恢复后复用。
  新浏览器和旧控件回归先失败，修后常驻原因、确认撤销、detached拒绝与业务草稿保持通过。

## 增量验证

以下Root最终运行互不重复的主验证合计307项通过，另受影响浏览器14项通过。未跑全量test。

```bash
.venv/bin/pytest -q tests/web_console/test_operation_budget.py \
  tests/web_console/test_core.py tests/web_console/test_model_calls.py --maxfail=1 --tb=short
```

46 passed，8.24秒。完整Git计划、实际UTF8/escaping精确预算与+1byte边界、超限无终态/临时文件、
损坏identity/digest/sequence/malformed仍拒绝，既有生命周期与诊断保持。

```bash
.venv/bin/pytest -q tests/web_console/test_transport.py \
  tests/web_console/test_legacy_rescue_acceptance.py --maxfail=1 --tb=short
```

54 passed，8.40秒。真实HTTP >2MB store reopen/list/detail完整读回、503脱敏、404 identity、
精确工程能力与审批事实保持。两个既有Starlette/httpx/anyio deprecation warning。

```bash
.venv/bin/pytest -q tests/contracts/test_json_schema_contracts.py \
  tests/domain/test_delivery_resolution_schema.py --maxfail=1 --tb=short
```

110 passed，1.66秒。wire Schema未修改，Console与resolution模型契约保持。

```bash
node --test tests/team_view/readiness.test.cjs tests/team_view/operation-capabilities.test.cjs \
  tests/team_view/engineering-wait.test.cjs tests/team_view/incremental-polling.test.cjs
```

83 passed，0.17秒，其中engineering-wait 38项。读取失败与runtime/Team/Project门禁、
当前文案与copy report、旧detached控件、事实恢复确认、一般表单draft/read状态保持。

```bash
NODE_PATH=/Users/zhangjunshuai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  node --test tests/team_view/browser/legacy-rescue.test.cjs
```

14 passed，16.28秒，真实Chrome仅拦截fixture API，不访问生产。单Operations失败与双API同轮
失败→关闭toast→常驻原因→同计划恢复→confirmation未勾选→独立精确批准；业务草稿与披露DOM保持。
Worker另跑browser/polling-state、async-boundaries、engineering-wait，14/14通过；没有安装新依赖。

Ruff check/format与strict Mypy对store、transport及其2个测试文件全部通过；node --check与
git diff --check通过。独立review最初的同时读取失败medium已修复、38项DOM与2项Chrome独立复核通过，
最终无未解决blocking finding。

### 额外探针的既有失败

扩展运行test_product_failure的auth用例期望MODEL_AUTHENTICATION_ERROR，却得到offline-codex
启动OSError对应MODEL_PROVIDER_UNAVAILABLE。该测试仍mock structured.subprocess.run，当前
structured client已经使用另一受控进程入口，fake executable不会启动。将HEAD8817b8b的完整store
实现隔离载入并替换已导出的store class后，精确auth用例仍出现同一失败；与本轮预算/HTTP/UI无关。
未为了扩大本轮检查修改无关adapter或该测试，没有运行真实模型。

## 真实存量只读复验

Root直接绑定既有目录的只读 `_current/_list_current`，没有constructor、lock创建、claim/start
或Host构造；通过进程内FastAPI TestClient加载本轮代码读取真实Operation，仅GET。
list与detail均HTTP200，287条完整记录可读，目标SUCCEEDED/READY，Operation和plan integrity通过。

- Operation SHA256：`62d91d5bb611b24fde16934f9586d1876732162e1ff8dff0d15a878b4ca5a21b`。
- Plan SHA256：`5a18365a045d1b31e3c98c773a0385002ab83d44c2bc63087016ac41b9ba3e3a`。
- 原操作3份JSON读取前后bytes SHA256完全一致，没有重写、截断、压缩或迁移。

这些HTTP200是新代码的进程内只读见证，不代表PID1797已经加载修复。旧服务未重启，生产接口仍
受旧reader影响；没有补造旧调用结果/停止、审批、新计划、Task状态或预算。

## 存量数据处置与用户恢复步骤

不需要改库或数据迁移；已有完整READY方案可直接兼容读取。所有Task/Run/checkpoint/操作链/审批/
现场和证据保持，用户无需重新创建需求或重复准备方案。

1. 暂停旧页面新操作，由工程维护按受控服务流程加载修复。本次旧实例已记sticky拒绝时，
   restart/resume不能解除；需按docs/operations/controlled-service-restart.md的维护升级边界核对
   旧服务/执行与保留记录后维护停止和加载，不能反复点击或删除记录绕过。该维护动作本轮未执行。
2. 新服务加载后刷新**原需求**，应重新读到已封存READY方案和“批准保留进度并继续原需求”。
3. 查看方案与实际停止确认；仅在其同机同账户本地、原调用及全部派生工具已结束等内容符合真实事实
   时，以工程职责勾选并批准。旧结果仍UNKNOWN，不将新调查伪称历史stop。
4. 后续新claim/Coder以及独立同candidate QA/Review成立后才算交付；本轮没有继续需求。

## 风险与回滚

16MiB是显式存储预算，不保证接受全部无限字段组合。列表仍读取完整历史/current result，
分页与重正文artifact引用属于后续独立设计，不截断当前审核绑定。旧服务sticky故障需要维护加载，
这不是新增数据故障，不会因重启自动批准或重新执行。

回滚时用受控服务流程停止已更新服务，revert本轮代码、加载并刷新；保留所有不可变记录与草稿。
回滚reader将恢复256KB限制，现有大记录可能再次不可读，因此恢复可用性需保留本轮兼容能力。

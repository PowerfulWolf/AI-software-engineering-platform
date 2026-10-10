# 后端增量验证记录

## 范围与结果

2026-10-10，恢复准备观察后端已完成定向验证。没有运行全量测试，没有操作、重启或向生产 ASE 提交请求。

```sh
uv run pytest -q \
  tests/web_console/test_preparation_progress.py \
  tests/web_console/test_core.py \
  tests/web_console/test_transport.py \
  tests/recovery/test_preparation_inspection_scope.py \
  tests/work_queue/test_execution_contracts.py
```

结果：**113 passed**，两条既有 Starlette/httpx deprecation warnings。新增测试文件自身包含 27 个测试。

覆盖 Schema 正反向与 scope/digest 验证；文件存储幂等、重开、篡改、symlink、计数/字节上限和独立非阻塞锁；授权、Task 封存、dispatch 提交、seed 核验及真实 Coder claim 的成功返回边界；观察失败不重复命令；ContextVar 重置；GET/404/405/503、Team 慢读并发、旧操作空观察和终态读取。观察存储重放保留首次时间与原文件字节。

```sh
uv run ruff check \
  src/ai_software_engineer/recovery/preparation_progress.py \
  src/ai_software_engineer/web_console/preparation_store.py \
  src/ai_software_engineer/web_console/core.py \
  src/ai_software_engineer/web_console/host.py \
  src/ai_software_engineer/web_console/transport.py \
  src/ai_software_engineer/recovery/entry.py \
  src/ai_software_engineer/work_queue/worker.py \
  tests/web_console/test_preparation_progress.py

uv run ruff format --check \
  src/ai_software_engineer/recovery/preparation_progress.py \
  src/ai_software_engineer/web_console/preparation_store.py \
  src/ai_software_engineer/web_console/core.py \
  src/ai_software_engineer/web_console/host.py \
  src/ai_software_engineer/web_console/transport.py \
  src/ai_software_engineer/recovery/entry.py \
  src/ai_software_engineer/work_queue/worker.py \
  tests/web_console/test_preparation_progress.py

uv run mypy \
  src/ai_software_engineer/recovery/preparation_progress.py \
  src/ai_software_engineer/web_console/preparation_store.py \
  src/ai_software_engineer/web_console/core.py \
  src/ai_software_engineer/web_console/host.py \
  src/ai_software_engineer/web_console/transport.py \
  src/ai_software_engineer/recovery/entry.py \
  src/ai_software_engineer/work_queue/worker.py \
  tests/web_console/test_preparation_progress.py
```

结果：Ruff、格式检查及仓库 strict mypy 配置均通过，mypy 检查 8 个文件。

## MySQL 恢复端到端验证限制

测试环境存在隔离 MySQL DSN；运行前已执行本地安全校验，只比较解析后的数据库名，确认与生产数据库不同，没有输出 DSN 或凭证。

曾尝试在 `tests/recovery/test_execution.py::test_recovery_complete_native_delivery_and_preserve_failed_history` 的三个参数化 case 中加入观察器验证。三个 case 均在 `recovery.propose`、任何新观察记录前失败：旧 `InterruptedFactory` fixture 直接返回失败，没有满足现行完整审计所要求的 continuation 与真实停止记录，报 `ContinuationRejected: continuation directory is missing or unsafe`，继而 `RecoveryRejected: 终态开发现场的完整审计未通过`。

没有放宽审计、伪造停止证据或使用生产数据库绕过 fixture。仅为该尝试添加的 `test_execution.py` 改动已经撤回，该文件无本任务 diff。故不能宣称真实 MySQL 恢复端到端场景已经通过；本次可复核的后端结果是上述 113 个直接增量测试。

## 存量数据处置

无需修改数据库或迁移既有 Operation。观察明细使用独立存储与只读 GET，不改 Operation hash chain、Task/WorkItem 状态、批准、claim 或旧执行证据。既有操作不倒填准备观察；空观察只表示未记录，不能推断命令未执行或授予继续权限。

以后真实启动、精确绑定恢复批准 scope 的操作才记录本次新增边界。现有需求仍按原恢复和审批契约推进；本任务没有重新批准、重复派发或修改旧需求。加载新代码应在活动执行结束或明确安全维护边界后受控重启，不能热替换正在运行的 Agent。

## 回滚

回滚新增观察模型、独立 store、API 及观察调用后受控加载。保留已封存观察文件、原 Operation/Task/审批与执行历史；观察不拥有执行权限，回滚不撤销批准、不改变 verdict、不自动推进需求。


## 前端与独立审核

Node新增10项通过，直接影响5文件Node174项此前通过；真实fixture Chrome4项root复跑通过，
覆盖慢Team独立刷新、换需求旧回调、空/旧服务/损坏、保留正文选择及草稿、1440/1024/390
排版和键盘导航，所有接口拦截为fixture、零非GET。root查看1440与390截图。
legacy polling-state旧selector定向修正，批准按钮必须直接可见并保留旧回调撤销断言。
FullGitRevision40/64和不同timezone offset的latest排序回归先红后绿，JS语法与diff检查通过。

独立后端review未发现阻断：逐项追到真实commit/return边界，27项新增测试独立复跑通过。
前端wire收到40/64SHA和offset排序两项反馈后完成修正。已知MySQLfixture限制仍保留；
以上结果不冒充生产恢复或K1已交付。

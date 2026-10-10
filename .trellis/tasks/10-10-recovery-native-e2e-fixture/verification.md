# 增量验证

## 原 fixture 红测

运行前通过 `require_isolated_mysql_test_database`，并按 typed `ProductionConfig` / sibling
`LocalRuntimeEnvironmentStore` 读取解析生产 DSN，仅确认库名与测试库不同；只输出布尔结果。
pytest 子进程只接收 PATH、LANG、LC_ALL 和既有 ASE_TEST_MYSQL_DSN，不传生产配置/模型凭证。

```sh
.venv/bin/python -m pytest -q \
  tests/recovery/test_execution.py::test_recovery_complete_native_delivery_and_preserve_failed_history \
  --tb=short
```

修复前结果：**3 failed in 6.23s**，参数为 `(False, False)`、`(True, False)`、`(True, True)`。
三者均在 `recovery.propose → read_terminal_workspace_snapshot → FileContinuationStore`
打开缺失 `continuations` 目录时失败：`ContinuationRejected: continuation directory is missing
or unsafe`，再封装为 `RecoveryRejected: 终态开发现场的完整审计未通过`。尚未进入恢复授权、
封存、dispatch 或 seed；红测与准备观察器没有关系。

此前一次安全 preflight 因诊断脚本误用不存在的 `ProductionConfig.load` 提前拒绝；该次没有
运行测试或打开数据库。改为正式 `from_file` 后，命名和库名隔离检查通过，再运行上述红测。

## 修复验证

第一轮真实原失败进程 + 完整 workspace snapshot 审计：**3 passed in 798.46s (0:13:18)**。
该轮已证明三个现行完整终态恢复 case 可以通过真实 start/stop，不需要放宽平台 gate。

随后补强 provisional Coder report / 平台 CandidateCommitSkill、五个持久准备里程碑及真实
claim Context 对齐；最终相同三个参数 case：**3 passed in 1019.32s (0:16:59)**，退出码 0。
strict seed、coder_reapply 和 legacy permissions + coder_reapply 均通过；没有扩展测试范围。
该结果证明完整 snapshot 恢复的现行安全契约及观察边界，不构成生产 f88 准备耗时优化证据。

修改文件质量检查：Ruff、format check 与 `MYPYPATH=src .venv/bin/mypy` strict 配置通过。
最初没有设置 MYPYPATH 的 mypy 命令把 editable 安装当成无 py.typed 第三方包，报告
import-untyped；改为明确仓库源码路径后检查通过，没有忽略类型错误。

最终测试完成后重复以下窄范围检查，均退出 0：

```sh
.venv/bin/ruff check tests/recovery/test_execution.py tests/recovery/execution_fixture.py
.venv/bin/ruff format --check tests/recovery/test_execution.py tests/recovery/execution_fixture.py
MYPYPATH=src .venv/bin/mypy tests/recovery/test_execution.py tests/recovery/execution_fixture.py
git diff --check -- tests/recovery/test_execution.py tests/recovery/execution_fixture.py .trellis/tasks/10-10-recovery-native-e2e-fixture
```

未运行整个 test_execution 文件、joint-child case 或全量测试；没有访问生产工作区、真实
provider 或执行生产审批/重启。真实 MySQL 测试只使用独占测试 DSN，按 autouse 前后清理。

## 独立审核与收尾

独立只读 reviewer 对真实 configured runner 的 start/stop 来源、进程组消失检查、
provisional Coder / 平台候选创建、legacy permissions 收紧、五个里程碑与真实 Context
claim 身份绑定完成静态审核，结论无阻断。共享工程知识由主 Agent 写入
`.trellis/spec/core/engineering-continuation.md`。

本次只修改测试夹具与任务文档，无生产契约变化、生产审批或数据库迁移，不需要处置存量
Requirement/Task。回滚仅撤回本任务列出的两个测试文件及任务文档；不改运行事实。

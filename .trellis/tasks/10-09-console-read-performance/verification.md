# 增量验收记录

## 结果

修复三个已确认问题：baseline/capture同读重复源码扫描、Console空闲claim全历史模型重放、
Team busy/deadline被通用MySQL提示覆盖。Schema/API与持久化事实不变，未部署/重启生产实例。
当前目录单Agent，未跑全量test。

## 测试与静态质量

```sh
.venv/bin/pytest -q \
  tests/context/test_source_inspection_scope.py \
  tests/context/test_source_secret_detection.py \
  tests/web_console/test_idle_replay.py \
  tests/web_console/test_core.py \
  tests/web_console/test_operation_budget.py \
  tests/team_view/test_engineering_history.py \
  tests/manager/test_verification_memory.py \
  tests/manager/test_execution_baseline.py \
  tests/manager/test_paused_baseline_service.py \
  tests/web_console/test_shutdown.py \
  tests/web_console/test_transport.py \
  tests/team_view/test_joint_history_snapshot.py \
  tests/team_view/test_task_read_snapshot.py \
  tests/team_view/test_live.py -m 'not mysql'
```

226 passed，6个MySQL集成用例按明确marker未执行。现有FastAPI/Starlette两项deprecation
warning与本修复无关。真实生产核验使用正式READ ONLY SQL，没有初始化/清理共享测试库。

```sh
node --check src/ai_software_engineer/team_view/app.js
node --test tests/team_view/readiness.test.cjs \
  tests/team_view/engineering-wait.test.cjs \
  tests/team_view/operation-capabilities.test.cjs tests/team_view/ui.test.cjs
NODE_PATH=/private/tmp/ase-rescue-ui-test-deps/node_modules node --test \
  tests/team_view/browser/polling-state.test.cjs \
  tests/team_view/browser/async-boundaries.test.cjs
```

轻量106 passed；真实Chrome 15 passed，全部API由fixture拦截，没有生产POST。
定向覆盖503 busy保持同一展开文档DOM，恢复后仅变更next_action；其余输入/帮助popovers、
选区、scroll、timestamp-only零mutation、晚到Project/编辑事实和旧审批失效保持。

下列8个Python文件分别通过`ruff check`、`ruff format --check`、`mypy --strict`：

- `src/ai_software_engineer/redaction.py`
- `src/ai_software_engineer/team_view/reader.py`
- `src/ai_software_engineer/team_view/engineering_history.py`
- `src/ai_software_engineer/web_console/store.py`
- `tests/context/test_source_inspection_scope.py`
- `tests/web_console/test_idle_replay.py`
- `tests/team_view/test_engineering_history.py`
- `.trellis/tasks/10-09-console-read-performance/read_probe.py`

`git diff --check`通过。红例和安全反例详见implement.md，未遗留调试日志/临时生产写入口。

## 真实存量只读对照

独立进程、顺序执行；旧服务PID33041仍运行，会有在线CPU竞争。baseline只从本地Git
读取四个旧模块到内存，不改变当前文件或运行服务。只构造ProductionTeamReader，沿既有
READ ONLY事务读取；Operation性能调用纯`_list_current`/`_operation_inventory_sha256`，
没有构造Host、claim工作、创建目录/锁、调用模型或写store。

```sh
.venv/bin/python .trellis/tasks/10-09-console-read-performance/read_probe.py \
  --config /Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json \
  --project project_ai-project_034252eb3595 --revision ab5dead
# 之后独立执行相同命令，去掉 --revision ab5dead；再次执行验证下一次读取仍完整校验。
```

| 指标 | baseline ab5dead | 修复后首次 | 再次独立进程 |
| --- | ---: | ---: | ---: |
| snapshot+to_wire秒 | 25.4233 | 4.5794 | 4.3186 |
| 实际源码扫描 | 14,848 | 67 | 67 |
| SQL execute次数 | 190 | 190 | 190 |
| SQL累计秒 | 0.2785 | 0.2792 | 0.2762 |
| Operation完整重放秒 | 2.6256 | 0.3206 | 0.2533 |
| Operation源码扫描 | 1,856 | 67 | 67 |
| idle完整bytes清单秒 | — | 0.1057 | 0.0888 |

首次snapshot耗时减少约82%；完整敏感信息扫描仍保留，只消除同一正文/路径的重复计算。
idle清单比旧每轮全模型重放约少96%的这部分耗时，不包含实际HTTP锁等待，不能当端到端保证。
没有在对照期间并行跑测试/大文件hash探测；两轮来源清单、requests=2/tasks=25、
全部290个Operation均一致。快照除`as_of`外canonical SHA相同：
`be4af415786006952ada55fc4946bfd019f32546a82f7f0e263123bb9996a29a`。
平台15,935个JSON / 688,207,263 bytes读前/后源清单相同：
`8ab8f7187129613574dcb558fcd56b7d099168b814fea244d20d5001ddf2a812`。
probe只输出数字、计数和摘要，不输出文档/源码/SQL/凭证正文。

## 存量数据处置

无需改库、迁移、截断历史、补证据、重建需求、重新批准或重置预算；本次未改变既有运行事实。
用户在空闲时受控加载本修复：

1. 确认没有正在执行的操作；使用`./scripts/ase-console-service.sh restart`，由既有drain/
   stop-proof机制判断可否安全重启。若拒绝，按其具体阻塞检查，不强杀、不再派发。
2. 浏览器刷新原Project，加载启动时冻结的新前端资产。busy/deadline会有具体提示；轮询
   保留展开内容。单独浏览器刷新不会给未重启的旧实例加载新Python/冻结资产。
3. 继续观察原需求。原有业务/工程审批与暂停事实仍有效，是否授权接续由用户明确决定；
   本修复不是继续执行授权，也不是旧UNKNOWN执行已经停止的证明。

## 已知风险和回滚

- 全历史bytes仍逐轮重验，数据规模增加或机器竞争仍可慢；没有把读取busy归结为MySQL故障。
  大型结果引用/分页及跨请求快照缓存不属于本次范围，不能原地截断历史。
- 无生产HTTP部署后测试；上述是同真实数据的隔离读取。没有重启服务或主动恢复需求。
- 回滚本修复提交后空闲受控重启、刷新浏览器恢复旧读侧行为。不会删除/重写Task、
  Operation、审批、候选、queue/lease或任何审计文件；旧重复扫描成本会随代码回滚恢复。

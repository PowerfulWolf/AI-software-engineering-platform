# 验证与交付说明

## 修复目标

完成同一需求的“保留合法开发进度并暂停 → 更新代码/原生工程规范仍暂停 → 明确继续 →
独立 QA/Review”公共路径。目标项目不限于 ASE 自身。平台运行版本与目标源码版本分开。

新增持久队列工程暂停、精确继续授权/释放、完整规范 epoch 与只读正文差异审阅、三角色与
知识 Context 的共同规则来源、跨服务中断的已授权待启动入口及多仓审阅状态隔离。
不重建 Requirement/Task/分支，不改原范围/权限/Task.base_ref 或历史 verdict，不重置额度。

## 增量验证

没有跑全量 pytest，没有调用生产模型。

- `uv run pytest -q tests/manager/test_execution_baseline.py tests/manager/test_execution_baseline_context.py tests/manager/test_execution_baseline_native_rules.py tests/manager/test_execution_baseline_reservation.py`：26通过。核心修改后另复测 public_service/inherits_rules：2通过。
- `uv run pytest -q tests/manager/test_execution_native_rules.py tests/context/test_native_sources.py tests/manager/test_execution_baseline_context.py`：17通过。三角色全文/知识投影完整性 guard 后复测6通过；结构化 native 与独立 sidecar 规则增量2通过。
- `uv run pytest -q tests/manager/test_paused_baseline_service.py`：1通过；精确规则批准、暂停、新更新不能RESUME、规则epoch继承、原分支/范围保持。
- `tests/work_queue/test_baseline_pause_mysql.py`：20个初始不同用例验证通过；pending READY/已领取/后续等待增量4通过。真实隔离MySQL，按单一串行测试通道执行。
- `uv run pytest -q -x tests/manager/test_production_execution_baseline.py -k pause_native_epoch`：1通过；原有其余7个公共基线回归通过。含授权落盘前后SQL崩溃、完整文件/索引漂移拒绝、SQL提交后Host启动前崩溃、精确重试、独立三角色同epoch/知识/候选。
- `tests/manager/test_legacy_rescue_delivery.py` 的本机停止PAUSE场景：1通过。组合路径从原UNKNOWN/READY救援方案，经原需求暂停、更新源码+README规则并暂停，再明确继续、QA PASS/Review APPROVE到DONE；旧继续拒绝、无额外额度、原分支现场与历史保留。
- `uv run pytest -q tests/team_view/test_pending_baseline_continue.py tests/contracts/test_baseline_pause_schema.py`：7通过。只读SQL快照和readonly store：仅授权文件无提示、精确已释放未领取提示、已领取和后续等待无提示；状态显示可接续而非无限等调度。
- Native rule GET/standalone/schema相关6通过；最后 product execution+native GET 19通过。GET不构造Host/不注册/不写仓库，完整delta/epoch错配拒绝。
- Engineering history24通过；Console legacy acceptance16通过。暂停/明确继续决定可审计，授权不冒充实际启动或验收，首次过时请求拒绝、已有精确决定允许重放。
- 相关DOM四个文件81通过；真实Chrome `tests/team_view/browser/legacy-rescue.test.cjs`最终18通过。完整暂停/规则审阅/更新/继续、双仓审阅互不清空、轮询保留内容、READY中断重试及无原Console Operation的CLI批准均覆盖。
- 全部40个修改Python文件 Ruff check/format通过；39个相关src/test严格Mypy通过；app.js语法及git diff --check通过。

独立只读审查发现的SQL已释放但前端无接续入口、多仓审阅缓存清空、pending replay现场重新
核验等问题均修复并补测。审查结论限于本次流程，不声称整个平台不存在其他Bug。

## 存量数据处置

本次没有生产SQL更新、K1源码/工作区变更、审批、继续、另建需求或服务重启。
保留原K1：task_dc5cf0aee44e5ffe0cb600557204e0d0；原run_9b76fb2865144f2abb6407923320ec4e；
Project project_ai-project_034252eb3595。

旧字段缺省时不写入新字段，旧Operation/READY方案/绑定bytes与digest兼容。新增SQL release表
由既有队列初始化路径追加创建，无需改写旧事实或手工迁移审批。

加载新版并刷新原需求后：
1. 原READY恢复方案精确确认实际停止前提，选择保留进度并暂停。
2. 目标注册仓库是单独克隆，应先取得需要的最新main提交对象；ASE服务升级不会自动同步克隆。
   这是仓库来源同步，不能手工rebase/clean保留的Coder工作区。
3. 在原需求更新代码版本，查看全部工程规范正文差异，精确确认并保存新方案，保持暂停。
4. 查看当前版本后明确继续。若服务在队列释放后启动前中断，点击“继续已授权执行”复用原决定。

生产加载仍使用现有受控服务维护流程。此次实现授权不包含替用户审批或启动K1。

## 风险与回滚

冲突仍需新的coder_reapply方案；显式结构化native规则变更仍要求重新编译/确认，不能被opaque
文本审批静默替换。缺失目标Git对象、活动执行、现场或索引漂移、上下文超预算均保留并拒绝。
尚未对生产K1执行该路径，真实业务验收留给用户加载新版后操作。

新记录生产落盘前可在空闲受控停止后回滚本代码提交。落盘后保持PAUSE/nativeepoch/release
读取能力，采用向前修复；不能让旧版本忽略暂停，也不能以git reset/clean、删表或改旧审批撤销
已经批准的代码更新。再次更新目标源码使用追加的精确工程方案。

最后一次相关纯契约/权限/历史/API增量组合验证：
`uv run pytest -q tests/domain/test_delivery_disposition.py tests/manager/test_delivery_wait.py tests/work_queue/test_baseline_history.py tests/team_view/test_engineering_history.py tests/web_console/test_legacy_rescue_acceptance.py tests/web_console/test_native_rule_review.py tests/contracts/test_baseline_pause_schema.py`
结果121通过；只有既有HTTP测试依赖弃用提示。最终Ruff40文件、Mypy39文件、JS语法和diff检查通过。

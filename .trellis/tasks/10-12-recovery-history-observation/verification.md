# Compact history observation 验证记录

日期：2026-10-12。代码位于隔离 integration checkout `ase-capacity-receipt`；未操作生产、
重启服务、运行模型、改库、审批需求或新建同名需求。完整测试留给用户，本任务只跑增量。

## 红测与可核实结果

先在compact实现前运行真实 Allocator→sealing→Builder service测试：

```text
test_real_allocator_keeps_all_reads_and_fences_but_decodes_ancestors_once
FAILED: assert decodes[ancestor] == 1; actual 32
1 failed in 1.62s
```

接入固定receipt后的同一service测试保留32次source观察、64次SQL/claim/no-start/capture检查、
两个分配fence，以及每路径原有两个inventory glob、一次regular preflight和一次Journal全读。
大字段长历史的相同祖先仅完整解码1次；每轮head仍独立完整解码/校验。第二fence测试在
build返回后、最终validate之前改变祖先，确认两个fence均到达且dispatch未发布。

分配fixture的capacity观察是明确side-effect，目标facts来自另一offline fixture，不宣称是
同一plan/source绑定。独立测试实际调用 NativeFacts.inspect→_read_source→精确capacity
reader，持久化真实fixture receipt，验证source/receipt/policy/history变化均拒绝；只有target
Git/compiler是显式fake。

验证另外覆盖：完整同mtime/size篡改、重新封祖先、缺first/middle、symlink/错名、新tail、
深拷贝、原Manager协调与approved product/integration批准/knowledge recheck/DONE后继规则；
compact/full退休端口对历史child命中、错误hash/owner、missing/foreign replacement和坏祖先
结果一致；Context先或journal先、多root实际累计512条、one-byte额度均完整fallback；
retained exception、callback关闭、copied thread和async child释放owner。

## 增量命令

```sh
PYTHONPATH=src .venv/bin/python -m pytest \
 tests/recovery/test_requirement_history_observer.py \
 tests/recovery/test_requirement_history_service_scope.py \
 tests/recovery/test_requirement_history_successors.py \
 tests/recovery/test_capacity_parent_journal_scope.py \
 tests/recovery/test_context_capacity_source.py \
 tests/recovery/test_context_capacity_sql.py \
 tests/recovery/test_context_capacity_entry.py \
 tests/recovery/test_record_read_scope.py \
 tests/recovery/test_preparation_inspection_scope.py \
 tests/manager/test_requirement_retirement.py \
 tests/manager/test_requirement_deletion.py \
 tests/manager/test_joint_journal_read_reuse.py -q --tb=short
```

作者结果：**126 passed in 59.79s**，未跑全量测试。

Ruff check/format只检查本任务5个源码和4个测试文件，全部通过；源码另以普通 `--strict`
验证，**Success: no issues found in 5 source files**。测试导入的既有fixture模块曾有typing
缺口（preparation fixture缺seed新端口由其owner随后修复，planner反馈fixture仍有既有
Protocol缺口），对owned5源码+4测试使用 `--strict --follow-imports=silent` 完整检查，
**Success: no issues found in 9 source files**。该参数只静默未列出的import模块诊断，
并未跳过本次owned文件检查。`git diff --check`通过。

独立 reviewer `/root/summary_result_scope_compat` 完成源码/契约静态复核与增量验证：
**PASS，无剩余 blocking findings**。独立6文件69项通过（73.57s）：observer、service、
successors、capacity-parent、record-scope及原Journal private-copy；Ruff owned9、源码5
strict mypy silent与diff check通过。PASS不代表生产延迟或RSS已得到保证。

## 限制、存量数据处置与回滚

这些结果证明固定codec、全读/新鲜事实和有界retained合同；未证明生产整段延迟或RSS峰值。
完整字节读取、head解码、Context目录读取和编译仍有成本，provider故障也独立存在。

存量数据处置：无需迁移或修改任何Requirement/Task/Operation/审批/现场。root在当前活动执行
完成后安排受控部署；原K1按既有public审批/继续路径使用，旧失败保持完整。不能为了性能
重建需求、重写receipt或清空worktree。回滚本任务内部observer/receipt组合即可恢复原完整
历史解码；durable bytes及原退休/parent规则保持有效。

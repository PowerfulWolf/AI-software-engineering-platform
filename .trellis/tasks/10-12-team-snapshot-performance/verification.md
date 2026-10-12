# Team snapshot 增量验证

- Base: `ec55d53498c97d2b99fcd230166ded2cd2a5c1c8` 最新集成工作区。
- 预修复真实投影复现：Plan/Start 各 2 次完整 decode、各 2 次完整文件读取；authority 2 次 decode，
  全部 4 条 timeline 保留。只使用临时 fixture，无生产/模型/共享 MySQL。
- 修复只改 reader 的 import 和公开同步 scope，保留既有 source inspection scope。
- 预修复回归 `test_snapshot_reuses_actual_projection_decoding_but_reopens_all_originals` 实际失败：
  snapshot 没有 recovery-record scope。随后新增 9 例第一次运行中 8 个安全回归通过；性能断言
  发现 Start 普通 history list 不使用 fixed port，已把期望正确收敛为 Plan 2→1、Start 保持 2。
  实际调用栈确认两路 Start 读取，未为满足指标扩大普通 list cache。
- Ruff check、format check、strict mypy（reader 与新增测试两个文件）通过；owner diff check 通过。
- 修正计数后的首例与既有 baseline/task/engineering/general record scope 增量：
  **41 passed in 156.93s**。前轮其余 8 个新增安全回归通过，合计 49 个相关不同用例通过。
- 独立 reviewer `/root/summary_result_scope_compat` 静态检查：**PASS，无 blocker**，确认 fixed
  codecs、fresh complete bytes/hash、deep-copy、owned scope 与 authority 读取不变；独立重复
  5 文件回归在后台继续。本次由 root 指示根据必要绿门固定提交，避免延长已安全停服的维护窗口。
- 执行命令（均增量）：
  `PYTHONPATH=src <venv>/python -m pytest -q --tb=line tests/team_view/test_snapshot_record_scope.py`
  首轮 8 passed / 1 性能过度断言失败；精确修正预期后运行
  `PYTHONPATH=src <venv>/python -m pytest -q --tb=line tests/team_view/test_snapshot_record_scope.py::test_snapshot_reuses_actual_projection_decoding_but_reopens_all_originals tests/team_view/test_baseline_snapshot.py tests/team_view/test_task_read_snapshot.py tests/team_view/test_engineering_snapshot.py tests/recovery/test_record_read_scope.py`
  得到 41 passed。`<venv>` 为主仓 `.venv/bin`。
- 有限 fixture 只证明重复 Plan 解码被消除，未测量真实 HTTP 端到端时间或长期 RSS，不能宣称
  前端 15 秒超时或内存报警已全部解决。实际部署后测量由 root 负责。
- 存量数据处置：无需改库、重写原始字节/审批/历史或新建需求。空闲受控重启后刷新原需求。
- 回滚：移除 reader 新 scope，恢复重复解码成本；持久化状态、审计和保留工作区不变。

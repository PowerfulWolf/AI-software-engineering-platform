# 实施与验证结果

代码只修改 Codex CLI 的 `_classify_cli_failure` 末尾未知默认分支和
`_recognized_cli_failure` 的显式服务故障识别，不改诊断来源选择、preflight或进程监督。
没有可信主诊断时保留 PROVIDER_UNAVAILABLE/false；明确HTTP408/500/502/503/504或
connection failed/refused/reset/timed out 保留有界临时故障语义。

- 新矩阵红：7 failed / 6 passed；绿色与原生CLI角色/权限/真实子进程一起：65 passed。
- provider provenance + unknown matrix：57 passed；原背景AUTH阴性断言仍拒绝AUTH，
  无main诊断由旧默认true修正为false，明确connection main由未知提升为显式服务故障。
- taxonomy公开Host真实child：unknown work3工程调查、work1真实BLOCKED均通过；
  原error/code/stop/noartifact完整保留，精确结果见相邻taxonomy任务。
- Ruff/format、strict Mypy、diff check通过；独立native Agent review无阻断。

实际增量命令（在隔离工作区使用主仓venv，`PYTHONPATH=src`）：

```text
python -m pytest -q tests/agents/test_cli_unknown_failure.py tests/agents/test_codex_cli.py
python -m pytest -q tests/agents/test_codex_provider_contract.py tests/agents/test_cli_unknown_failure.py
python -m mypy src/ai_software_engineer/agents/codex_cli.py tests/agents/test_cli_unknown_failure.py tests/agents/test_codex_provider_contract.py
```

存量数据处置：无需改库，不重写任何历史error/transient、Run、stop、retry、Task或审批。
旧等待须经Root另行交付的公开受控结案继续原Requirement。代码回滚保留所有审计事实；
回到旧classifier会重新允许未知退出被误当临时，优先前向修复。

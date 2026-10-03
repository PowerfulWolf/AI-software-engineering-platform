# 增量验证记录

## 结果

`ase verify-propose` 现在支持重复的 `--python-test` 精确节点选择，并在模型调用前将其解析为
typed `PytestSelection`。缺少 `=` 或验收标准时 fail closed，错误提示为中文；旧的无参数调用
仍传递 `None`，没有改写历史计划或审批。

```text
.venv/bin/pytest -q tests/recovery/test_cli.py tests/agents/test_candidate_source_binding.py tests/recovery/test_candidate_verification.py tests/recovery/test_verification_routing.py --tb=short
43 passed in 2.97s

.venv/bin/ruff check <changed Python files>
passed

.venv/bin/ruff format --check <changed Python files>
2 files already formatted

git diff --check
passed
```

未运行全量测试。已有无受控执行回执的旧 verification plan 仍保持失败事实；修复部署后必须以
精确 selectors 创建新计划并重新审批。

## 存量数据处置与回滚

无需迁移或直接改库。回滚为回退本次 CLI、文档和测试提交；保留所有旧计划、QA FAIL、运行记录和
审批。回滚后只能使用既有正常恢复入口，不能重放已消费的验证计划。

# 实现与增量验证

固定 pytest 的 traceback/summary/capture/color/live log/逐用例 verbosity 开关，trusted guard 输出索引绑定计数和最多16项白名单错误类别/数字码。全部32节点计数保留，200个失败也能保留诊断；跳过仍非零，setup/teardown分开，collection错误显式计数。任意异常文字、路径、argv和参数ID不进入摘要。4096字节执行输出上限及整流截断脱敏不变。

独立Reviewer发现候选ini能通过verbosity_test_cases覆盖-q并回显secret-bearing skip；已固定该ini值为-1，32长节点FAIL/SKIP实机runner回归覆盖候选verbosity=2。

验证命令：`.venv/bin/pytest -q tests/manager/test_python_verification_runner.py tests/recovery/test_python_mysql_execution.py`：27 passed、2 explicitly-opted sandbox fixtures skipped，5.83s。Ruff check/format、两个文件strict Mypy、git diff --check通过。未跑全量。

存量数据：旧回执整流清空的输出不可恢复，不修改已封存QA FAIL或其MAJOR业务finding。已有K1后继Coder因provider失败留下现场，保留dirty inventory并通过新的精确恢复审批继续；新runner只能在新hash-bound计划获批后用于验证。

回滚：revert此提交并重提案；保留所有旧计划、审批、invocation、回执和候选。主机与目标仓库不执行任意异常文本；摘要仍只是命令事实，不是verdict。

# 增量验证

先运行 `pytest -q tests/manager/test_joint_journal_read_reuse.py`：1 failed / 4 passed，重复 current 对同字节调用 decoder 两次，复现不必要的重复验证。

修复后：

- `pytest -q tests/manager/test_joint_journal_read_reuse.py tests/manager/test_joint_contracts.py`：33 passed。
- `pytest -q tests/recovery/test_native.py::test_native_source_is_verified_read_only_and_rejects_corruption tests/recovery/test_native.py::test_joint_parent_cannot_be_omitted_from_source_lineage`：2 passed（真实 Git/MySQL，独立测试库）。
- 四个变更源/测试文件 Ruff 和 mypy 通过；format/diff 提交前复验。
- 暖缓存仍拒绝篡改、重新封存祖先、缺失初始记录及 symlink；返回 attempts 修改不会污染缓存；514 条历史仍完整返回且缓存最多 512。

未运行全量测试。平台还未加载此补充修复，K1 仍在真实 Coder 阶段；不以 fixture 验收替代 QA/Review。

回滚：空闲时回退平台提交并重启。无存量修复脚本、无直接改库和清理操作。

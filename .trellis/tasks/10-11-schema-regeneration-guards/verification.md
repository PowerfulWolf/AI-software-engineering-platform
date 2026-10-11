# Verification

Six independent legacy cross-field guard cases were red before the generator fix
and green afterward. The repair generator now reuses the existing canonical
`sync-legacy-rescue-schemas.py::guards` function without invoking its guarded main.
Tests run the real generator twice in an isolated root without an old console file,
prove byte stability and exercise cross-field bad inputs independently of shape.

The regenerated repository Console output was copied from an isolated run; no
other frozen Schema was regenerated in the repository. A direct HEAD comparison
found **0 missing existing allOf guards**. All five canonical engineering guard
definitions match, including the new knowledge guard and optional parent field.

After the parent's legacy parent-binding model addition, the related Python group
passed **53 tests in 2.33 seconds** (before the final canonical-parent regression
was added):

```sh
.venv/bin/python -m pytest \
  tests/contracts/test_repair_schema_generation.py \
  tests/contracts/test_local_legacy_rescue_schema.py \
  tests/contracts/test_baseline_pause_schema.py \
  tests/domain/test_knowledge_preparation_retry_schema.py -q
```

最终新增 canonical engineering/optional parent 回归后，generator 专项 **11 passed in
1.68 seconds**；其他相关文件未变化，未重复运行无关测试。

The original full Console payload/status contracts passed **2 tests, 100 deselected
in 0.62 seconds**:

```sh
.venv/bin/python -m pytest tests/contracts/test_json_schema_contracts.py -q \
  -k 'console_operation_states_satisfy_the_canonical_schema or console_operation_schema_rejects_relative_roots_and_incoherent_status'
```

Ruff and strict mypy passed both changed script/test files. `git diff --check` is
clean. No MySQL/full suite, production operation or database rewrite occurred.

## 存量数据处置 / rollback

仅静态Schema生成回归，服务端domain原来仍拒绝同类坏输入；无需修库或回填旧 Operation。
保留恢复后的完整静态守卫，不回滚到缺少 legacy allOf 的文件。已有需求和历史继续使用原
精确权限与proof，不能以本次修复重新批准旧记录。

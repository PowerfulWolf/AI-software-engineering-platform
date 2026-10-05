# Schema 漂移验证

现有 exact 联合 Schema/model 用例在原 HEAD 因空 `$defs` 失败。新增真实输入契约用例
通过 PlanTestItem 领域校验后，向五个静态 bundle 的 PlanTestItem `$ref` 提交独立
命令验证/native UI 检查两个合法输入，并要求任意未授权字段仍被拒绝。
正确 fixture 的 red 为 8 failed/2 passed；原生 project-stage-defs 已正确，保持无修改。

只重生成六个受影响静态 model 契约，保留 `$id`/`$schema` 和原键序；没有模型字段、
审批、服务行为或 additionalProperties 宽松化变更。

```sh
.venv/bin/python -m pytest -q tests/manager/test_verification_schema_embedding.py tests/manager/test_joint_contracts.py::test_joint_schemas_are_in_sync_with_models tests/knowledge/test_schema_parity.py tests/manager/test_joint_planner_test_matrix.py
# 38 passed
.venv/bin/ruff check tests/manager/test_verification_schema_embedding.py
.venv/bin/ruff format --check tests/manager/test_verification_schema_embedding.py
MYPYPATH=src .venv/bin/mypy tests/manager/test_verification_schema_embedding.py
# all passed; 未运行全量
```

独立只读 reviewer 核对六个静态 Schema 的所有语义差异、新增输入用例及规范：没有
额外属性约束放宽或未经模型支持的字段。独立执行 exact 联合 schema parity、新增
嵌入测试和 knowledge schema parity 共 27 passed in 0.74s，可提交本任务范围。

## 存量数据处置

无需改库、重写旧产物或旧审批。修复的是静态 schema 对现有合法字段的拒绝；旧模型、
原有必填字段与校验语义未变。K1 安全恢复由独立的 joint-verification-parity 任务通过
公开精确 CONTINUE 完成；本任务不能把旧 invalid 设计当有效输入。

## 根因与防复发

共享模型已扩展但多个静态嵌入未同步，属于跨层变更传播缺口。exact parity 保持不变；
补充真实 nested verification 输入和额外字段负向用例，docs 与 Python code-spec 已
记录复用 `$defs` 的同步要求。回退本提交仅回退静态契约/文档，不删除 durable 历史。

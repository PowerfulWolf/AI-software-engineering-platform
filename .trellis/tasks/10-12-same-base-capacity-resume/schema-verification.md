# 同源容量恢复的独立 Schema 核验

独立提交所有权仅限 `tests/contracts/test_same_source_capacity_schema.py` 与本说明。主作者另授权在生成脚本的 `digest_gate.then` 增加唯一的 `required: [purpose]`；该小块保留给主作者统一提交。五个发布 Schema、其余生成脚本、后端领域校验及其测试仍由主作者负责；不使用测试数据库、不调用模型或操作生产。

## 覆盖契约

- 新 `context_capacity_resume` PROPOSE 无用户指定目标 SHA，默认省略 `target_base_ref`；显式 null 保留现有 optional 字段兼容语义。拒绝任意 SHA、coder_reapply，以及无目标的旧 source_rebind；原有带目标 source_rebind 仍可校验。
- 遍历所有发布/从实际脚本重新生成的 Plan、Binding 嵌入图，校验独立 capacity purpose、完整 receipt、未调用且已预留的 continuation、精确 PAUSE 与工程决定、保留 draft，拒绝其它恢复证据或 supersedes 混入。
- Binding 带 capacity receipt 时必须显式声明 purpose，不能落回缺省 source_rebind。每个完整 binding 同时跑 Pydantic 与独立 JSON Schema 验证。
- 代码负责 Schema 无法表达的动态字段相等约束：execution base/source 与原值相等，完整变更清单 digest 相等。
- 真实旧 source-rebind binding 的容量字段缺省/显式 null 后序列化字节、完整 wire 与 SHA 不变。
- 临时复制生成脚本运行真实 regeneration，两次生成幂等；检查每个 published embedding 的生成形状及 allOf gates 与新输出一致。仅用于 wire 校验的 receipt sentinel 不作为任何运行恢复事实。

## 已执行结果

2026-10-12 初次增量 **9 PASS / 2 FAIL，29.21 秒**。两条精确 RED 都是相同真实缺口：发布与新生成的 `ExecutionBaselineBinding` 带容量 receipt 但移除 purpose，被 Schema 接受，而 Python 因默认 source_rebind 正确拒绝。已交主作者补生成脚本 digest gate 的 `then.required=[purpose]` 并重新生成；不弱化测试。

初次 Ruff、格式、Mypy 本文件通过；全量测试不在本次范围。

2026-10-12 委派修复后：唯一的 `then.required=[purpose]` 已补齐。在独立临时镜像复制当前全部发布 Schema 与两个真实生成脚本，重新生成镜像发布文件；测试及 regeneration fixture 的 Schema 根目录指向该镜像。**11 PASS，11.29 秒**。镜像路径为 `/var/folders/xr/6y57gfc94c77b4729m06xgjr0000gn/T/ase-capacity-schema-verified-eopadiap`，实际重新运行两次生成的幂等检查与每个镜像 published embedding 的 parity 均通过。源工作树的发布 Schema 未被该核验修改，主作者仍需统一 regeneration 后运行本文件，以完成正式发布文件的一致性检查。

临时镜像运行必须使用绝对 `PYTHONPATH` 指向当前开发树的 `src`。第一次镜像尝试沿用相对 `PYTHONPATH=src`，子进程切到镜像后加载了已安装的旧模型，产生 **8 PASS / 3 FAIL**；这次无效环境结果未作为最终验证。修正绝对路径后重新复制、生成并运行，得到上述 11 PASS。通过驱动预导入模块时 pytest 输出一次 assertion-rewrite warning，不影响实际断言。

最终静态核验：测试与生成脚本 Ruff/格式通过，测试 Mypy 通过。没有全量测试或测试 MySQL 运行。

```sh
PYTHONPATH=src .venv/bin/python -m pytest tests/contracts/test_same_source_capacity_schema.py -q --tb=short
MYPYPATH=src .venv/bin/mypy --follow-imports=silent tests/contracts/test_same_source_capacity_schema.py
.venv/bin/ruff check tests/contracts/test_same_source_capacity_schema.py
.venv/bin/ruff format --check tests/contracts/test_same_source_capacity_schema.py
git diff --check
```

存量数据处置：本次仅 Schema 和纯 wire 回归，没有数据迁移或生产写入。回滚本测试/说明不会改变已有审批、历史 hash 或运行事实。

# 增量验证与存量处置

## 验证结果

先加入契约测试；缺少新类型使 collection 明确失败。加入模型后，Builder 回归证实新计划
虽已批准，后继 Task 的 engineering_policy 仍为 None。接线后该场景与旧计划兼容场景均绿。

最终离线增量命令：

```sh
.venv/bin/pytest -q -m 'not mysql' \
  tests/recovery/test_task_policy_builder.py tests/recovery/test_task_record.py \
  tests/recovery/test_authorization.py tests/recovery/test_current.py \
  tests/recovery/test_models.py tests/recovery/test_store.py \
  tests/recovery/test_preparation_inspection_scope.py tests/recovery/test_baseline_wire.py \
  tests/recovery/test_execution_records.py tests/recovery/test_cli.py \
  tests/recovery/test_git_integration.py
```

首轮完整增量结果 **126 passed, 1 deselected in 8.69s**，其中核心新授权/record/authorization
55 passed。独立 Schema 审查补充两个缺失版本边界后，核心三文件复跑 **57 passed in
0.70s**；其余生产代码未再次改动，没有重复扩大测试。
未运行全量测试、MySQL、真实模型或生产交付。

Ruff format --check、Ruff check 通过，范围为下列 8 文件：

```text
src/ai_software_engineer/recovery/{models,task,entry,current,records}.py
scripts/sync-recovery-target-authorization-schema.py
tests/recovery/test_task_policy_builder.py
tests/recovery/test_task_record.py
```

同范围 `MYPYPATH=src .venv/bin/mypy ...`：**Success: no issues found in 8 source files**。
`git diff --check` 通过。

Schema check_schema、所有局部 refs 解析、旧/新/legacy 三种正例和六种 retry/continuation
版本反例通过；重复同步 bytes 不变。Schema SHA：
`0b2b3b95f69d9e02ec906dce25c2c60ddc35cb6853d9e63938a6f3fd30665e84`。
旧 19 个 defs 完整保留（RecoveryPlan 仅多 property），根 union 和旧 allOf/权限约束不变。

独立 reviewer 指出，JSON Schema 的 properties const 不会要求字段存在。先补 `{}` 和
v1 wire 省略 schema_version 的负例，复现 **2 failed, 4 passed**（Pydantic 都已拒绝，
Schema 错误接纳）。在同步脚本和 Schema 的目标 continuation 节点补
`required: [schema_version]` 后，六个负例全绿，脚本二次同步 bytes 不变，相关两文件
Mypy、Ruff lint/format 及 diff check 再次通过。未改变运行时或任何旧授权。

## 旧字节兼容证据

### Console审批与组织契约

root在manager.py对持久计划的审批facts仅按实际新授权显示有界工程处理；仅当冻结
continuation存在时说明按原额度保留进度续跑，不扩大文件范围、不替代独立验收、不授权
合并或部署，未知执行不会直接续跑。增加同原新旧矩阵的目标授权维度，目标32/32通过，
对应两文件Ruff/format/strict Mypy通过；独立check再次32/32绿且文案范围核验无发现。
delivery-recovery、engineering-continuation及architecture/contracts已同步可执行契约、
错误矩阵、存量处置和回滚。真实Configured执行组合在独立任务增量验证，不提前宣称完成。

只读加载 git HEAD 的旧 models/records 实现，与新实现对同一 `/offline/legacy-repository`
fixture 比较：旧 RecoveryPlan 的 to_wire、model_dump_json、嵌套 Envelope 的
model_dump_json、RecoveryTaskRecord 和其 Task 的 model_dump_json 全部相同。
旧计划摘要保持 `5da471132a22fa4d7463a68bfdd4927f6c6d63db4a0b4148e32783b81d2294a7`。
新目标授权和内部无值可选字段在不使用 exclude_none 的递归 dump 中也省略。

## 存量数据处置

本改动不改库、不重写已批准计划、历史 Task/Operation/Run、QA/Review verdict 或保留工作区。
现有 K1 要获得完整授权时，不能重放原批准然后自动注入 policy，应按以下路径处理：

1. 部署并重启包含本修复的版本，保留旧计划、批准、Run 和完整现场。
2. 在同一需求从最新真实原 Task 重新准备恢复计划。平台必须核验真实停止、精确工作区及
   目标基线；本授权补齐不替代这些事实检查。
3. 由可信 ENGINEERING 操作主体查看新计划。确认该计划包含目标授权且 source budget
   来自原 Task，未使用当前配置扩额；如原 Task 无 retry，v2 仍应缺失。
4. 通过正常精确批准入口批准新 plan SHA。旧批准不用于新摘要。仅在该授权和当前事实
   双重复核通过后继续原需求，保留关联的历史执行链，不另建相同 Requirement。
5. 检查新封存的 RecoveryTaskRecord 两项 policy 与批准方案相同，再使用既有派发/角色
   执行链。知识准备本地超时另由其专属修复解决，不能把无 native-start 当停止证明。

这些步骤由根代理/用户在授权范围内执行；本子任务未代操作生产或批准新方案。

## 风险与回滚

新增字段是授权读取契约。尚未写入新计划时可回滚代码；写入后回滚必须保留新字段读取
兼容，不能删授权事实、删历史或把旧批准等同新批准。旧版本不识别新字段时应 fail closed。
无 ENGINEERING 主体或 legacy 无 frozen retry 时能力刻意保持受限，需要通过合法的新
计划/预算契约处理，不能手工补库。本任务不保证解决独立知识超时、实际进程停止、冲突或
环境验证失败，也不更改 QA/Reviewer 独立验收。

# 增量验证（待 root 独立审查）

## RED / GREEN

先运行新增 test_current_journal_copy.py：2 failed, 13 passed。失败均为真实四条日志链中
cold/warm current 深复制次数为 4，期望 1；使用原始 model_copy side_effect 保留真实行为。
提取私有完整读验遍历后，同两例次数为 1；cold/warm history 仍复制完整四项。

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest \
  tests/multi_directory/test_current_journal_copy.py \
  tests/manager/test_joint_journal_read_reuse.py \
  tests/team_view/test_joint_history_snapshot.py -q -p no:cacheprovider
```

结果：31 passed。包括冷解析与热复用、每次完整 read_bytes、追加、同长度/mtime 篡改、
初始/中间记录缺失、祖先重封导致后继链断裂、文件名及 symlink 拒绝、嵌套字典隔离、
空读取，以及原有 514 条链验证后的 512 项 cache bound。

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest \
  tests/manager/test_joint_contracts.py \
  tests/manager/test_joint_verification_admission.py \
  tests/manager/test_verification_memory.py -q -p no:cacheprovider
```

结果：43 passed，1 failed。唯一失败为既有 test_joint_schemas_are_in_sync_with_models，
单独重跑仍失败：requirement-checkpoint.schema.json 的 $defs/DeliveryNextAction/enum 是
disposition 操作列表，实际 JointCheckpoint.model_json_schema() 此处是 stage 操作列表。
本任务未修改 model、enum 或 Schema，已交 root 在本任务所有权外处理，不宣称该合同通过。

精确路径为 schemas/requirement-checkpoint.schema.json → $defs/DeliveryNextAction/enum；
其引用者为 $defs/ProjectDeliveryCheckpoint/properties/next_action。实际引用 Python model 是
manager.delivery_checkpoint.ProjectDeliveryCheckpoint，字段类型是同模块的 DeliveryNextAction；
静态定义却含 domain.delivery_disposition.DeliveryNextAction 的八个值。

额外 baseline 复现：子进程通过 git show HEAD:src/ai_software_engineer/multi_directory/store.py
读取原实现，在内存中的 store 模块重新定义原 JointJournal，并确认没有 _validated_history，
随后 pytest.main 单独运行同一 Schema 同步测试，仍为 1 failed。没有改写工作区或 HEAD 文件。
这证明本任务的 current/history 遍历优化不是该 Schema 漂移的原因。

## 静态检查

对 store.py 和新增测试运行 Ruff check、Ruff format --check、
Mypy --strict --follow-imports=silent；两文件均通过。git diff --check 通过。
仅新增测试曾有两处行长问题，已 formatter 修复。

## 实际边界

这是离线真实模型/文件计数回归，不是生产恢复端到端延迟测量。没有生产读写、模型调用、
SQL、批准、服务操作或 commit。read-memory-lifecycle.md 由其他 worker/root 集成，避免冲突。
存量字节、当前恢复计划及其目标基线保持不变，无需迁移；回滚见 prd.md。

## root 独立复核

完整复核store差异：原逐项读取/hash/model/路径/前驱与cache逻辑逐行保留，公开current和history
均耗尽完整私有iterator；只有返回值深拷贝的数量变化。history仍给每项独立副本，current只给
最终副本，无domain authority或跨轮询latest决定。独立选择cold/warm复制次数、每次fresh读取、
同长度/mtime篡改及返回嵌套dict隔离五例：5 passed，10 deselected；没有阻断发现。
相关getter契约已同步read-memory-lifecycle.md。Schema既有失败另由10-10-joint-schema-alignment
跟踪，不能据此宣称全部合同已通过。补丁的受控部署和原需求端到端验证由root继续。

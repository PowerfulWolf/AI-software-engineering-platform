# 实现与验证

## 根因与修改

普通恢复调查与 Orchestrator 均同时检查失败类别和 `error.transient`，但源码基线 collector
的 `_reservation` 对直接封存的失败 outcome 只检查 `TRANSIENT_CODES`。因此
`PROVIDER_UNAVAILABLE / transient=false` 可被误写为新的服务故障预留，甚至在普通工作
额度耗尽时获得不应有的接续身份。

生产代码只增加 `and outcome.result.error.transient`。无新增恢复能力、Schema、预算、
数据库或权限；合法中断 receipt 与独立 AUTH 前提修复 proof 原样保留。

## 红绿与增量验证

先新增真实 KnowledgeRecordStore outcome → ProductionBaselineFactCollector._reservation
的参数化回归。旧代码结果 **8 failed, 9 passed**：四个允许类别在有剩余和已耗尽普通工作
额度时，全部八个 `transient=false` 场景错误放行。真正 transient 与非允许类别回归已通过。

修复后执行：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q \
  tests/manager/test_execution_baseline_reservation.py \
  tests/manager/test_execution_baseline_invocations.py \
  tests/manager/test_stopped_provider_retry.py
python -m ruff check src/ai_software_engineer/manager/baseline_production.py \
  tests/manager/test_execution_baseline_reservation.py
python -m ruff format --check src/ai_software_engineer/manager/baseline_production.py \
  tests/manager/test_execution_baseline_reservation.py
MYPYPATH=src python -m mypy --follow-imports=silent \
  src/ai_software_engineer/manager/baseline_production.py \
  tests/manager/test_execution_baseline_reservation.py
git diff --check
```

**66 passed in 106.70s**；Ruff、format、strict Mypy 两个文件、diff check 通过。
四个允许类别覆盖 transient true/false、普通额度耗尽/未耗尽、distinct identity、work count
保持、exact replay、不支持类别、原 Task/retry facts 与已保存 JSON bytes 不变。
仅跑上述三个相关测试文件，无全量测试、生产 SQL、真实模型或服务操作。

## 独立复审

Root 转达只读 reviewer `/root/native_truncated_diagnosis` 的独立检查结果：无阻断；确认
gate 正确、已有 proof/receipt 路径不变，四类错误 true/false、额度、重放和历史保持覆盖，
spec 明确存量不退款。该结论是 reviewer 的审查，非本实现者自行产生角色 verdict。

## 存量数据处置

不迁移、不直接改库，不改旧 Task、original outcome、capture stop、预算或工作区。当前
真实 nontransient K1 失败仍保存完整现场和原预算，不能通过 source rebind 申请 provider
退款；其合法工程处置与输入问题由独立任务解决。本次仅封住未来误分类入口，不宣称需求
已恢复或交付。修复等待服务 idle 后由 Root 受控集成加载。

## 风险与回滚

新行为有意拒绝此前错误放行的 nontransient 基线接续。持久化 wire 未变，无新兼容负担。
回滚可撤销这一提交，但会恢复不安全的 code-only 计账，不得以回滚绕过拒绝。若发现已
发布的错误预留，须独立核对其精确事实和批准历史；本次不推断或自动修写这类记录。

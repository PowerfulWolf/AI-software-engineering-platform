# 验证与存量处置

真实故障位于每个request重新创建provider adapter的生产生命周期：首轮合法progress后，
第二轮重新调用仅首Run允许的seed.authorize，模型前被拒绝。新增真实Git测试在未接入scope
选择时精确复现 `Codex worktree violated the execution precondition`，接入后通过。
旧回归仅复用adapter，无法锁住该问题。

## 增量结果

```text
.venv/bin/pytest -q tests/agents/test_initial_admission_scope.py \
  tests/agents/test_codex_cli.py tests/agents/test_responses.py
76 passed in 8.26s
```

13项新增覆盖真实首轮progress、每轮新adapter、Codex/Responses续跑、extra path/HEAD/checkpoint
漂移拒绝、QA/Review clean candidate返工，以及默认unwrapped baseline每Run重新核验并拒绝
发生变化的当前授权。6项文件Ruff、format --check、strict Mypy均通过。未跑全量测试。
生产恢复工厂仅对terminal seed/interruption显式包装，fake factory原端口保持。

## 存量数据处置

原K1与本次恢复Task均保持原终态，不重置、不重放已消费edc70计划、不改SQL。
最新合法progress art_coder_1cbfcc0ef2253347573fa3b712088a76及27文件现场保留。
受控加载修复后，在同Requirement公开Continue准备新精确恢复方案，核对完整现场/新基线，
再批准接续；审批、原失败和人工维护归因保留。独立QA/Review仍为完成前提。

## 限制与回滚

本测试为真实Git配离线provider，不表示K1候选已通过或交付。
provider失败且已有合法dirty progress的分类仍需另行诊断，未借本修复声明已解决。
回滚本scope选择和工厂接线，保留所有durable facts；旧代码可能再次拒绝正常later Run。


独立代码审核未发现阻断。审核指出旧live continuation规范漏掉accepted progress，已与
首Runwrapper签名/默认baseline每Run/每轮新adapter验收一起修正。原有权限与重放保护保留。

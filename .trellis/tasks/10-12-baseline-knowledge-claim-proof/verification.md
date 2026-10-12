# 增量验证与存量处置

内部接口：`read_failed_knowledge_claims(state, task, item, claims, scope, requirement_id,
queue, require_step, no_start_reader) -> tuple[KnowledgeOnlyClaimProof, ...]` 只读完整持久化事实。
`CapacityInputReader.require_claim_not_started(UninvokedClaimBoundary, allow_later_claims=True)`
复用原主调用、native、route、raw artifact 否定扫描；不发布 stop/capacity receipt。
`BaselineInvocationProof.knowledge_only_claims` 为空时省略，新 proof kind 不能混入主调用证据。
Public API、Schema、MySQL、审批、attempt/retry 账本未改变；公共 facts 仍只引用完整内部
`baseline-quiescence` SHA，所以无需重新生成静态 Schema。

| 情形 | 结果 / 执行点 |
| --- | --- |
| 合法独立HTTP records+FAILED知识准备 | 内部quiescence精确接纳；HTTP仅本地round-trip事实 |
| 实际离线native nonzero | 真实owned process-stop重读，原claim/source/Context精确 |
| 缺 outcome / 独立 observation、孤立记录、错误键 | 拒绝，原状态与文件不写 |
| 替换/追加foreign claim、source/snapshot漂移 | 拒绝，不能以重封hash建立执行权威 |
| 后续start lookup key返回另一个合法later claim | shared no-start扫描拒绝 |
| 主start lookup key返回另一个合法claim | 原调用分支拒绝 |
| 真实知识503后attempt2容量等待 | public基线提案、exact PAUSE、独立RESUME，原Task DONE |
| 既有capacity rounds1/2及删除marker反例 | 原精确停止记录与不变Task/attempt路径仍通过 |

验证命令：

```sh
uv run ruff check src/ai_software_engineer/manager/knowledge_invocation_proof.py src/ai_software_engineer/manager/capacity_input_reader.py src/ai_software_engineer/manager/baseline_production.py tests/manager/test_baseline_knowledge_claim_proof.py
uv run ruff format --check src/ai_software_engineer/manager/knowledge_invocation_proof.py src/ai_software_engineer/manager/capacity_input_reader.py src/ai_software_engineer/manager/baseline_production.py tests/manager/test_baseline_knowledge_claim_proof.py
uv run mypy src/ai_software_engineer/manager/knowledge_invocation_proof.py src/ai_software_engineer/manager/capacity_input_reader.py src/ai_software_engineer/manager/baseline_production.py tests/manager/test_baseline_knowledge_claim_proof.py
uv run pytest tests/manager/test_baseline_knowledge_claim_proof.py tests/manager/test_execution_baseline_invocations.py tests/knowledge/test_invocation_receipts.py tests/knowledge/test_invocation_native.py -m 'not mysql' -q --tb=short
uv run pytest tests/manager/test_baseline_knowledge_claim_proof.py::test_public_baseline_after_real_knowledge_failure_preserves_original_delivery -q --tb=short
uv run pytest tests/manager/test_public_context_capacity_baseline.py -q --tb=short
```

public新例最终 1 PASS / 18.03s；既有两例最终 2 PASS（前次组合运行 56.34s 总耗时中唯一失败为新夹具缺少成功consultation，修正为真正structured round-trip并独立重跑后通过）。新例验证原Task attempt2、原一条transient failure不变；暂停不修改Task/events；继续后Coder、QA、Reviewer三Agent独立候选验收DONE。无生产模型或网络调用，MySQL仅使用guard校验的隔离测试DSN，窗口结束已释放。不跑全量测试。

独立review确认并修复：所有lane意图完整收尾；snapshot lookup hash精确绑定；追加foreign claim不能跳过真实ownership；later main/start与所有original_claim lookup键的lease一致。review离线red probes已变green。最终源代码与新测试 strict mypy、Ruff、format 全通过；4个相关非MySQL测试文件 78 PASS / 12.90s（1 mysql deselected）。独立review已放行：13新负例/正例 PASS、此前44相关回归 PASS、实际red probes复跑均green。

存量数据处置：无需改库，不伪造结果/stop/退款，不新建需求。原K1全部旧事实保留，发布后parent通过同一个需求重新准备最新main精确方案，再执行PAUSE和单独RESUME。该child未操作生产、未审批或继续K1。已有原记录不完整时保持阻塞。回滚在新方案前revert本次代码；已发布的追加quiescence摘要、审批和执行历史保留，不因回滚授权再次消费。

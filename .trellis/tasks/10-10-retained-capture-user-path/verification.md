# 验证与存量处置

## 结果

仅运行增量测试；未运行全量测试。当前修复尚未部署时，原 K1 仍为同一 Task，
IMPLEMENTING revision 17 / attempt 7，当前 WorkItem 为 WAITING_DEPENDENCY。
真实原停止是 30 分钟 local_execution_limit / TIMEOUT，不能说是缺少停止记录。

- backend/domain/history/reconcile 五个受影响套件：131 passed。
- 最终 stop observation / capture refusal / historical handling selectors：9 passed。
- 最终 source scanner + Git mutation capture：155 passed，27.31 秒。
- scanner scope 扩展：123 passed；包括标准库逃逸、动态 builtin 和 __builtins__ 拒绝。
- Context builder / baseline context / native v2：36 passed，132.86 秒。
- Node engineering-wait：47 passed；同 proof 的诊断变更更新实际增量 DOM。
- 14 个修改 Python 文件 Ruff format --check 通过；对应 Ruff、生产源 strict Mypy 通过。
- git diff --check 通过。独立 reviewer 复核了 scanner、停止授权边界、历史 hash 兼容和 UI 签名。

原保留 Coder 工作区只读真实 capture → wire roundtrip → verify_mutations 成功：
27 个变更文件、342336 patch bytes。该验证不写 receipt，不批准或继续，不改 Task/queue/Git。
首次 probe 忘记传入 Task semantic branch mapping，recovery 正确拒绝 default branch identity；
修正 composition 后使用 durable Task.branch_name 再验证，无现场变动。

浏览器实测暂受 Codex 浏览器认证不可用限制；尚不能声称真实页面视觉验收通过。
已完成真实应用 JS 增量 DOM 和操作绑定测试，部署后还需核对实际页面。

## 存量数据处置

没有 SQL 改库、状态重置、新建需求、伪造停止、修改 verdict 或清理原工作区。
保留原 invocation/start/stop、失败 handling 和所有 claim/attempt/history。
新代码能读旧 wire/digest，新诊断追加新的 immutable facts，不覆盖旧记录。

为保留源码通过安全封存，在用户委托的外部维护权限下精确修正了一处无效凭证测试样例：
tests/learning/test_recovery.py 的 token="wrong" 改为 token=""，保留拒绝断言。
该动作不属于 ASE Manager/Coder 自动能力，记录 HumanActionEvent MODIFY_TESTS 和本任务中
精确 before/after hash、完整 inventory、原停止 digest、不可变维护计划与完成记录。
真实 Task lock 和 queue idle fence 内完成；仅该路径改变，Task/queue/预算/verdict 未变。
因此本案例不能报告为完全自治 ADR。不要再次执行 fixture_correction.py；它绑定旧 hash，
第二次执行会拒绝。后续仍需原 Coder、独立 QA、Reviewer。

局部 K1 并发回归测试在原有 CollectionLedger.claim / _sealed(CollectionJob) 的 SOURCE_INVALID
处失败，发生于修改样例之前；不能称该业务测试通过。业务缺陷应由原 Coder 修复、QA/Review
独立验证，外部平台维护不代写业务候选或 verdict。

## 后续恢复与回滚

先修复源码基线 proposal 的原执行事实收集接线，再在空闲时受控重启。
公开 PROPOSE_EXECUTION_BASELINE 保存真实原进度并提出最新 main 的精确计划；审阅原生规范变化；
EXECUTE_EXECUTION_BASELINE continuation_mode=pause；明确 RESUME 后才运行 Coder。
不能先 HANDLE 自动接续过旧 source；不能手工 rebase/reset 原 Coder 工作区。

代码回滚保留审计与草稿。新增 collection_failure 记录一旦存在，行为回滚必须保留新字段读取
和 Schema/history 支持，旧 strict reader 会拒绝该字段；禁止删除/改写事实使旧版读取成功。

## 根因与防复发

1. 源码扫描把类型注解、数据字段引用和可信随机生成误当密钥值；完整 AST 的窄 syntax 例外
   与实际 RHS/default、强凭证特征检测分离。模块逃逸和动态执行不能获得可信构造例外。
2. 停止证明与完整进度封存被耦合；共享 exact stop validator，但停止永不等于恢复授权。
3. UI 只有只读 INSPECT，失败后缺少 HANDLE；显式重新处理入口与实际能力、精确事实绑定。
4. 增量 DOM signature 漏掉新增诊断；展示消费的诊断与 capability 都必须纳入更新签名。
5. 本次不能证明通用敏感源码自动纠错能力；外部 intervention 要审计并影响自治归因。
   组织知识已同步 engineering-continuation、live-team-view、legacy-execution-rescue。

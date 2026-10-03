# 完整记录 QA/Review 打回与 Coder 返工历史

## 问题

Coder 进入 QA 后，QA `FAIL` 会把 finding 回送 Coder；QA 通过后 Reviewer 仍可能 `REJECT` 并再次回送 Coder。当前 Team View 的任务详情只显示摘要，读者看不到 QA/Review 的具体原因，也无法核对下一轮 Coder 是否消费了 finding。跨 successor/remediation Task 的历史还可能只看到当前一轮，用户观察到执行记录固定只有八条。

## 目标

在只读 Team snapshot 和任务详情中呈现完整、可重算的交付执行历史：每次 Coder、QA、Reviewer Run；每个状态事件；QA/Review 报告的 PASS/FAIL/APPROVE/REJECT；finding 的 code、message、文件/行、recommendation、evidence ID；Coder 输入的父 Artifact、supersedes、changed files、测试和 candidate SHA；以及 successor/remediation Task 与当前 Task 的关系。展示必须区分当前轮和历史轮，并保留 source URI、Artifact SHA、Run ID 和 Task ID。

## 范围

- 扩展 `TimelineEntry.details` 的只读投影内容，保留 immutable Artifact 的 lineage 和受控报告摘要。
- Team View Reader 聚合同一 native delivery 的历史 Task checkpoint，避免 successor/remediation 轮次丢失；不改变状态机和 durable store。
- TaskView 增加完整执行历史字段，浏览器任务详情展示所有历史记录和质量反馈。
- 同步 Team snapshot Schema、Live Team View 规范和增量测试。

## 非范围

- 不写回 Task、StateEvent、Artifact、Evidence、Evaluation、Assignment、Lease、Operation 或 verdict。
- 不创建并行 DAG、合并分支或自动批准；不把 Operation 当作角色执行事实。
- 不翻译任意业务 finding 原文，不删除审计所需的原始信息；平台生成的状态/阻塞标签继续使用中文。

## 验收标准

1. 多轮同 Task 和跨 successor/remediation Task 的记录按时间完整返回，数量不受固定上限影响。
2. QA FAIL/Review REJECT 条目显示报告状态、候选 revision、finding 原文、位置、命令/测试和 evidence ID。
3. 后续 Coder 条目显示其输入的 QA/Review Artifact ID、supersedes 的旧实现 Artifact、changed files、测试结果和新的 candidate SHA；UI 明确显示“已接收上轮反馈”或“未发现可关联反馈”，不自行判定修复正确性。
4. 旧数据和空 findings 兼容，敏感文本仍经 redaction，URI/digest 以文本渲染。
5. Team snapshot JSON Schema、Python projection contract、Node UI contract 和相关增量测试通过。

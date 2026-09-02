# T033 PRD：Reporter Agent/Skill

## Goal

先验证 deterministic Handoff/Projection 是否已经满足交付表达；只有确有按用户语境重组内容的需求
时才增加 Reporter Agent。Reporter 永远只读 verified facts，不能创造事实、改变 verdict 或隐藏失败。

## Acceptance Criteria

- [ ] 用真实 T032 handoff 定义至少三类用户交付视图与缺口；
- [ ] 若 deterministic renderer 足够，记录“不引入生成式 Agent”的结论与测试；
- [ ] 若需要 Agent，Context 仅含 verified stage/delivery artifacts，输出引用所有关键 source IDs；
- [ ] Reporter 无 Task/Artifact/verdict/store write port，无代码 worktree；
- [ ] 输出遗漏 BLOCKED、QA FAIL、Review REJECT 或人工动作时 fail closed；
- [ ] snapshot/markdown/JSON 正反例和注入安全测试通过。

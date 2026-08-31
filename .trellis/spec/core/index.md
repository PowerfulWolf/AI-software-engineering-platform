# Core Spec Index

## Pre-Development Checklist

1. 阅读 [`architecture.md`](architecture.md) 的 Scope、Signatures、Contracts 和 Validation Matrix；
2. 阅读 [`contracts.md`](contracts.md) 的角色权限和 artifact/evidence 契约；
3. 编写 Python 代码前阅读 [`python-runtime.md`](python-runtime.md)；
4. 对任何跨层字段变化同步检查 `schemas/*.json` 与 `docs/contracts.md`；
5. 对状态、Context 或 Git 变化分别检查 `docs/state-machine.md`、`docs/context-routing.md`、`docs/git-worktree.md`；
6. 先补 contract tests，再接入真实模型或外部服务。

## Quality Check

- [ ] 所有新增接口都有输入/输出和错误行为；
- [ ] 所有状态迁移都可由事件流重放；
- [ ] 所有 artifact 都有 source revision、manifest、evidence 和 integrity；
- [ ] 至少有一个 Good、Base、Bad fixture；
- [ ] 完成后把新模式写回本层 spec。

## Files

- [`architecture.md`](architecture.md)
- [`contracts.md`](contracts.md)
- [`python-runtime.md`](python-runtime.md)

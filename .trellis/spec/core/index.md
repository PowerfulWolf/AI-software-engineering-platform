# Core Spec Index

## Pre-Development Checklist

1. 阅读 [`architecture.md`](architecture.md) 的 Scope、Signatures、Contracts 和 Validation Matrix；
2. 阅读 [`contracts.md`](contracts.md) 的角色权限和 artifact/evidence 契约；
3. 编写 Python 代码前阅读 [`python-runtime.md`](python-runtime.md)；
4. 对任何跨层字段变化同步检查 `schemas/*.json` 与 `docs/contracts.md`；
5. 对状态、Context 或 Git 变化分别检查 `docs/state-machine.md`、`docs/context-routing.md`、`docs/git-worktree.md`；
6. 先补 contract tests，再接入真实模型或外部服务。
7. 修改 `ase project ...`、MySQL、生产模型或 fallback 前阅读
   [`production-team-host.md`](production-team-host.md)。
8. 修改公司归属、项目注册或需求项目工作空间时阅读 [`company-workspace.md`](company-workspace.md)。
9. 修改联合交付入口、子仓投影或集成验证时阅读 [`multi-directory-delivery.md`](multi-directory-delivery.md)。
10. 修改实时团队视图、只读 store 或 HTTP 入口时阅读 [`live-team-view.md`](live-team-view.md)。
11. 修改中断改动捕获或终态恢复时阅读 [`delivery-recovery.md`](delivery-recovery.md)。
12. 修改组织队列、Dispatcher 或 Lease 生命周期时阅读
    [`persistent-work-queue.md`](persistent-work-queue.md)。

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
- [`production-team-host.md`](production-team-host.md)
- [`company-workspace.md`](company-workspace.md)
- [`multi-directory-delivery.md`](multi-directory-delivery.md)
- [`live-team-view.md`](live-team-view.md)
- [`delivery-recovery.md`](delivery-recovery.md)
- [`persistent-work-queue.md`](persistent-work-queue.md)

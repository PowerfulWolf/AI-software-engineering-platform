# Implementation plan

1. Extend WorkItem and workforce JSON Schema for Run-level queue identity and scope.
2. Add typed queue commands/results and a `PersistentWorkQueue` Protocol.
3. Implement MySQL/InnoDB repository with atomic claim, owner-fenced lifecycle and expiry recovery.
4. Add a bounded Dispatcher tick using PortfolioScheduler and ModelRouter.
5. Add positive, negative, replay, expiry and concurrent MySQL tests.
6. Synchronize README, architecture/orchestration docs, AGENTS.md and Trellis contracts.
7. Run formatter, lint, mypy, targeted tests and full regression.

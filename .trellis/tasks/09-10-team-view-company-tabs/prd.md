# Team view company tabs and task states

## Goal

Make the read-only team dashboard answer three questions without ambiguity:

1. Is a member working, waiting for their stage, or unassigned in the selected company?
2. Which tasks are active, blocked, or completed?
3. Which company owns the displayed work?

## Acceptance criteria

- Enabled members with no non-terminal assignment in the selected company display `空闲中`.
- The copy explicitly states that assignment-derived idle does not prove process liveness.
- Tasks appear exactly once under `执行中`, `阻塞中`, or `已完成`.
- Prepared companies appear as tabs and selecting one reads only that company's snapshot.
- Existing loopback, origin, read-only and no-secret guarantees remain intact.

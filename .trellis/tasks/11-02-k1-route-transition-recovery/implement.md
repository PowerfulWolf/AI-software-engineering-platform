# Implementation sequence

1. Add a red test at the baseline public resume boundary for CLI-to-Responses drift; implement the pre-consumption guard.
2. Add an exact K1-shaped fake/SQL fixture for expired no-invocation claim, retained baseline and dirty draft. First prove no settlement or successor currently exists.
3. Add a typed settlement with queue/Task fence and immutable record. Verify replay and all negative cases.
4. Add dedicated RecoverySource variant, full current-facts reader and Schema synchronization; route public Continue to exact proposal and existing approval/new Task pipeline.
5. Run public fixture through new Responses Coder, QA and Review. Recheck production K1 facts before any live settlement, publish under controlled pause, approve via the public interface, then follow through to accepted handoff.

Allowed paths for this engineering task are the exact manager, queue, recovery, web-console, Schema, tests and `.trellis/spec/core/` files identified by each milestone. No K1 ProductSpec, Design, Plan, old Task record, old dispatch or captured draft body is edited by this platform patch.

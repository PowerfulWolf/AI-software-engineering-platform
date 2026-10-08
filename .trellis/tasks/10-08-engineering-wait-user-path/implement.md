# Implementation tracking

- Backend worker owns Manager/Console/policy/queue contracts.
- UI worker owns current/historical guidance, stable exact controls and browser fixtures.
- Root owns invocation result reconciliation, durable start/stop capture, specs, integration and validation.
- Independent reviewer cannot write code or approve its own implementation; it reviews the final diff.

## Verification and limits

Actual commands, results, data handling and rollback are recorded in [verification.md](verification.md).
The final combined Python selection passed 223 tests; additional Console/Schema tests passed 174,
and isolated MySQL queue consumption passed 20. The joint Host composition test verifies that a
parent product command addresses a native child continuation scope. No full repository suite or
production delivery was run.

The product path is now: user selects “让平台处理中断” → the Manager service collects facts once under
the current Task/queue fence → the platform either records a policy-authorized handoff to the original
Supervisor or presents a Chinese maintenance/engineering decision record. It never asks a product user to
enter a lease, process stop, hash, retry cause or shell command. Legacy waits with no trustworthy start/stop
ledger remain `PLATFORM_ATTENTION`; they are preserved for maintenance and are not fabricated into timeout
or checkpoint evidence. Host SIGKILL/orphan-process observation remains outside v0.1.

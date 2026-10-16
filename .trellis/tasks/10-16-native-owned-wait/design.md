# Contract and failure matrix

Existing signatures remain unchanged:
`SubprocessCodexCommandRunner.run[_observed](...) -> CodexInvocationResult` and
`QueuedDeliverySupervisor.run(...) -> RuntimeRunResult`. No Schema changes.

Native owned-process uncertainty must become CodexExecutionUnconfirmed and then
ContinuationExecutionUncertain. Cleanup remains bound to the actual captured Popen; a
successful later cleanup may publish its real stop, but never erase initial uncertainty
or fabricate a final AgentResult. The supervisor must also catch a genuine raw
OwnedProcessesUncertain from trusted outer evidence/save boundaries and use the same
existing WorkerDeliveryFailureControl.wait fence as typed continuation/command uncertainty.

| Input | Result |
| --- | --- |
| Active native observation uncertain, cleanup really stops child and seals actual stop | Typed uncertainty; no invented outcome/cause or retry |
| Owned uncertainty in outer artifact/evidence finalization | Existing owner-fenced EXECUTION_UNCERTAIN wait and lease release |
| Child remains live, pipes open or save unconfirmed | Preserve registry uncertainty and no successful-stop claim |
| Ordinary RuntimeError | Existing error classification, not owned uncertainty |
| Sealed invocation-start with absent outcome on reclaimed WorkItem | No new model call; record honest existing uncertainty |

The precise original OS failure in production is not yet evidenced. All-system enumeration
bounds and same-SID unreadable processes are possible triggers, not proven root causes.
The observation safety rule itself is unchanged; only its typed routing/queue lifecycle is fixed.

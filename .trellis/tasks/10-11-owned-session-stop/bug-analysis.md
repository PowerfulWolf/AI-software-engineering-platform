## Bug Analysis: leader/group stop and durable finalization were incomplete

### 1. Root Cause Category

- **Category**: E — Implicit Assumption, B — Cross-Layer Contract and D — Test Coverage Gap.
- **Specific Cause**: original PGID absence plus leader reap/EOF was treated as complete ownership
  termination. A silent same-SID peer in a different PGID survives all three. The registry also needed
  an explicit boundary linking real process completion to the consumer's actual durable record save.

### 2. Why Fixes Failed

1. Checking only the original group omitted a peer's legitimate PGID change; the real native red
   regression failed with a surviving child before the new controller existed.
2. Checking only current SID membership would miss an already observed birth later using setsid.
   Retained observed identities now reject that escape; stored-proof reads check the same identities.
3. Clearing on helper return was insufficient for evidence put/run seal/verification receipt failures.
   Nested trusted scopes now retain ownership until the true durable boundary and propagate it to
   proxy threads. No consumer is assumed complete merely because an executor returned.
4. A final protocol review found repeated confirm or new execution after confirm could clear earlier
   observations. Both real-command regression cases failed first; an irreversible invalid latch now
   keeps the whole finalization scope uncertain even if the caller catches that protocol error.
5. Two preexisting native-UI tests used mocked Popen objects, so the new actual-Popen requirement
   correctly rejected them. Those fixtures now mock only their trusted ownership seam; production
   checks remain strict. No runtime relaxation was made for mocks.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Architecture | one actual-Popen controller for currently registered cleanup consumers | DONE |
| P0 | Runtime | bounded full SID/birth/boot checks before signals and final publication | DONE |
| P0 | Runtime | unknown capture/inspection/escape/save/protocol failures retain Host blocker | DONE |
| P0 | Architecture | actual typed store put/seal confirms bounded nested finalization; explicit worker inheritance | DONE |
| P0 | Test Coverage | real silent multi-PGID, TERM resistance, known setsid escape and durable-save barriers | DONE |
| P0 | Contract | optional proof omitted from all legacy dumps; ten schema copies and fresh generator guarded | DONE |
| P1 | Memory | capture failure stores no exception; history/references bounded and scope links released | DONE |
| P1 | Documentation | executable scope/signatures/error matrix and recovery reasoning guide | DONE |
| P1 | Independent review | root checks maintenance patch before integration/deployment | PENDING |

### 4. Systematic Expansion

- **Similar Issues**: native/structured execution, policy-bound tools, Swift/Python verification,
  proxy pipe workers, read-only Git/OS helpers and DEVNULL UI tools shared the incomplete predicate.
  They now use the same existing registered ownership seam; unrelated unregistered subprocess
  infrastructure is not silently brought under a new permission model.
- **Design Improvement**: distinguish actual session stop, EOF, pipe-worker completion and durable
  publication. No one proxy/thread/leader fact can substitute for the conjunction.
- **Process Improvement**: reproduce real OS descendants and actual storage barriers before claiming
  controlled restart readiness. Keep unknown historical facts untouched; runtime code changes cannot
  retroactively strengthen a stop or justify a recovery approval.
- **Boundaries**: unobserved setsid escape and atomic query/signal containment remain outside this
  proof. Linux real-runtime and MySQL execution remain untested by this isolated task.

### 5. Knowledge Capture

- [x] `.trellis/spec/core/owned-session-stop.md`: executable contract and existing-data handling.
- [x] `.trellis/spec/core/{controlled-service-restart,engineering-continuation,index}.md`.
- [x] `.trellis/spec/guides/recovery-thinking.md`: full ownership and durable save checklist.
- [x] `docs/architecture/contracts.md`: additive proof and finalization contract.
- [x] `.trellis/tasks/10-11-owned-session-stop/`: PRD, design, verification and handoff.
- [x] Template check: this repository has no `src/templates/markdown/spec` tree to sync.
- [ ] Commit/integration: root owns this after independent review; isolated work is not yet deployed.

# Verifier checkout lifecycle

## 1. Scope / Trigger

Production delivery retries, verifier adapter caches, partial checkout creation and process restart.
Delivery attempt is not workforce allocation identity. One Task may produce several distinct candidates.

## 2. Signatures

```python
DispatchRoleWorktreeCoordinator.open_verifier(
    dispatch, role, candidate_revision, definitions, *, attempt=1, recover=False
) -> RoleWorktreeBinding
DispatchDeliveryAgentAdapter.run(request: AgentRequest) -> AgentResult
```

No new wire fields, environment variables, SQL migration or permissions.

## 3. Contracts

- Ordinary request Task must equal dispatch Task before any role executes. Standalone
  `VerificationReservation` retains the source Task for request/Context/artifact provenance;
  its separate execution Task owns checkout and workforce capacity. Validate the request against
  `source_task_id`, not `task_id`, and permit only QA/Reviewer in this mode.
- For ordinary delivery, QA/Reviewer checkout attempt equals `AgentRequest.attempt`.
  Frozen dispatch assignment remains attempt 1 and still validates Agent/model/role identity.
- Each verifier opens independently; a missing peer directory is not corruption.
- Every run reopens the exact registered detached checkout, verifies full candidate SHA and rejects
  dirty state before constructing/running a provider. Adapter cache is keyed by `(role, attempt)`.
- Coder continues in its existing attempt-01 branch. A separate `VerificationReservation` verifies
  one candidate and retains attempt-01 for its approved executor/evidence path contract.
- Old attempt directories are historical evidence. Do not reset, overwrite or migrate them.
  A clean new-attempt checkout is created from the exact input candidate. Same-attempt drift fails closed.
- Clean-only cleanup may remove bindings opened by the current adapter, never dirty evidence.

## 4. Validation & Error Matrix

| Input/state | Result |
| --- | --- |
| Different ordinary Task or different verification source Task | `ProductionConfigError` before checkout/provider |
| Standalone verification request uses source Task | Accept source provenance; checkout remains under execution Task |
| Different candidate, new delivery attempt | Fresh detached per-role checkout and adapter |
| Different candidate, same attempt | `WorktreeRevisionDrift`; preserve old directory |
| Current verifier directory dirty | `DirtyWorktree`; no model invocation or reset |
| Only QA directory exists after crash | Recover QA independently; create Reviewer when needed |
| Wrong Git registration, symlink or role | Existing Git identity/path rejection; no repair guessing |

## 5. Good / Base / Bad

Good: QA rejects v1; Coder commits v2; QA and Reviewer independently read v2.
Base: retry/restart on the same attempt opens the same clean exact checkout.
Bad: use a role-only adapter cache or fixed attempt-01 for all candidates; force checkout to silence drift.

## 6. Tests Required

- `tests/manager/test_verifier_worktrees.py`: real Git, distinct candidates, cached/fresh adapter,
  independent partial creation, QA/Reviewer same-attempt drift and dirty rejection/preservation.
- `tests/manager/test_verifier_retry_mysql.py`: production Host/queue, QA FAIL → Coder v2 → QA PASS
  → Reviewer APPROVE → DONE; exact v2 revision, released leases, unchanged main checkout.
- Keep role-workspace, standalone verification-routing and recovery suites passing.

## 7. Wrong vs Correct

Wrong: `self._adapters[role]` with one `qa-attempt-01` directory for all revisions.
Correct: derive the directory from the request attempt, recover/inspect it on every invocation, then
reuse only its role/attempt-bound adapter. Provider failure must never cause candidate identity drift.

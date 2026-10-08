# Bug analysis: legacy recovery had no usable local engineering decision

## 1. Root cause category

- **B — cross-layer contract**: the new controlled service shutdown protocol only proves its own
  lifecycle. It cannot supply missing stop/outcome records for an invocation from an older binary.
- **E — implicit assumption**: original invocation-start has no PID/PGID/device identity. Lease
  expiry, free task lock, idle console or absent server PID do not prove derived tools ended.
- **D — coverage gap**: an isolated containment helper can pass while public Console preparation,
  original Task queue publication and subsequent QA/Review traversal remain unreachable.

## 2. Why earlier fixes did not solve the user path

1. Recording new controlled shutdown facts improves future execution, but leaves the existing old
   UNKNOWN unchanged. It cannot retroactively establish an old process stop.
2. Requiring a later OS boot gave a strong engineering containment option but made it the only
   route, even when a responsible operator could confirm cessation of all original local work.
3. A preparation exception hid a normal unmet prerequisite as an operation failure. Returning
   typed WAITING check facts makes a useful next step visible without manufacturing a plan.
4. Review found re-proposal could return an approved local plan after a later boot without
   repeating its local survey. Rebinding/recollecting the sealed observation fixes READY semantics.
5. That recheck exposed a legitimate new historical binding contaminating the current pre-binding
   quiescence digest. Current rescue facts retain their exact original proof; later historical
   traversal validates and cites the saved binding. Both crash paths now pass public fixtures.

## 3. Prevention mechanisms

| Priority | Mechanism | Completed action |
| --- | --- | --- |
| P0 | Typed distinction | Separate OS reboot from local operator cessation, mutually exclusive exact fields |
| P0 | Runtime fencing | Real task lock, all ACTIVE claims SQL fence, fresh same-boundary survey and full inventory |
| P0 | Honest history | Keep old UNKNOWN; append immutable engineering authority and SUPPLY_EVIDENCE event |
| P0 | Public regression | Same Task/branch real Git + isolated MySQL + claimed native Coder/QA/Review fixture |
| P1 | UI guards | Capability v3, stale plan closure/confirmation reset, WAITING/READY/approval distinction |
| P1 | Schema parity | Both methods, absent/active survey, confirmation exclusivity and READY-without-plan negatives |

## 4. Systematic expansion

The scanner is deliberately an auxiliary observation, not a generic proof of historical cessation.
It never signals discovered processes or reads their environment, and stores only hashed boundaries
and fixed blocker codes. New PID coverage, high-resolution birth, incomplete query/output/permission
and owned-query shutdown uncertainty fail closed. The full old boot contract remains supported.

Exact immutable records must be pinned before fresh collection. Fresh timestamps and unrelated
process changes do not change a plan digest; genuine boundary or scene changes still reject.
Already consumed facts must replay without obsolete surveys or duplicated allowance.

## 5. Knowledge capture

- Updated `.trellis/spec/core/legacy-execution-rescue.md` with signatures, fields, matrix and gates.
- Updated `.trellis/spec/guides/recovery-thinking.md` with the historical/new-observation distinction.
- Updated user recovery and controlled service upgrade instructions, including rollback compatibility.
- This repository has no `src/templates/markdown/spec/` tree to synchronize.

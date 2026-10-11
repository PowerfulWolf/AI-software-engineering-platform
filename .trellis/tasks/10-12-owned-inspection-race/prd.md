# Darwin process inspection exit race

## Goal and evidence

The integrated public same-base delivery fixture once stopped after a successful QA outcome with
`OwnedProcessesUncertain`, before any Reviewer model route. Its inner error was not preserved.
One serial diagnostic rerun passed; 300 actual Git commands with record finalization and a bounded
1,500-child / 2,000-sweep exit probe also did not reproduce that original failure. Do not claim a
proven explanation for that fixture from those observations.

A separate deterministic OS boundary is actionable: `getsid(pid)` sees a live process, the following
Darwin BSD birth query returns a short result without a reliable ESRCH errno, and a fresh kernel
SID query confirms that the process disappeared. The old implementation rejects that confirmed
absence. Only fresh ESRCH may classify absence; denied, incomplete, still-living and recycled
identities remain unknown. No retrospective birth or stronger stop proof is created.

## Scope and acceptance

- Own `owned_sessions.py`, focused inspection tests and this task/spec documentation in this isolated
  checkout. Other agents are working; do not revert their changes or edit main/production facts.
- Record the race test failing before implementation and passing after it.
- Cover errno 0/ENOENT, denial, short birth query with a living/recycled PID and real process exit.
- Keep current active-owned, known-birth escape, complete-enumeration and signal gates unchanged.
- Run incremental inspection/session/finalization tests, Ruff and scoped strict mypy only.
- Do not run another MySQL fixture concurrently or operate ASE production.

## Rollback and existing data

Revert this narrow code change before new invocations at an idle controlled maintenance boundary.
There is no record/schema/digest migration or old-stop backfill. Root owns deployment and existing
delivery continuation; the original fixture's exact first reason remains unobserved unless a later
diagnostic reproduces it.

# Bounded production role timeouts

## Goal and evidence

Real recovery run `run_f76e3034c3ae49f1babd42ceb5f5b92a` was terminated at the
hard-coded 600-second Coder limit after modifying all 15 authorized files but before tests,
commit, or Artifact production. The repository's full test suite itself takes roughly six
minutes, so the current whole-role budget is not sufficient for a complex implementation.

## Requirements and acceptance

- Keep every production role bounded by the existing `AgentDefinition` maximum.
- Give Coder 1,800 seconds for analysis, implementation, verification, commit, and Artifact output.
- Give QA and Reviewer 1,200 seconds each for independent verification and Artifact output.
- Keep the deterministic Orchestrator at 60 seconds.
- Apply the same contract to native and recovery delivery composition.
- Preserve timeout failure classification, dirty-worktree retention, no-artifact behavior, and
  `max_retries=0`.
- Add fast contract coverage plus real Git/MySQL offline recovery coverage.

## Scope

This repair changes role execution budgets only. It does not resume the failed Task, import its
dirty files, weaken isolation, add adaptive scheduling, change model routing, or authorize merge,
push, or deployment. Risk-aware and operator-configurable budgets remain future work.

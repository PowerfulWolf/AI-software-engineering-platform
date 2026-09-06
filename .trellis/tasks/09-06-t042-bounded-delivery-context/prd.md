# T042 Bounded production delivery context

## Goal
Repair the offline-reproduced ContextBudgetExceeded before Coder in self-iteration round 2.
Astra repairs the platform only; no feature implementation or manufactured delivery evidence.

## Acceptance
- ProjectProfile remains immutable and complete. Context-only projection replaces exhaustive
  language marker lists with counts, bounded samples and full-profile provenance; all native
  rule references and build-system facts remain available unchanged.
- Runtime accepts an explicit input budget, default 12,000; production explicitly uses 32,000.
  Required sources, artifacts and policy are never truncated. Oversize input still fails closed.
- Manifest records the actual selected budget; no global increase or automatic budget retry.
- Offline tests cover marker-heavy projects, explicit runtime propagation and required overflow.
- Any role's context overflow becomes durable BUDGET_EXHAUSTED/BLOCKED via the existing
  orchestrator transition, preserves prior artifact/candidate facts and cannot auto-retry.
- Replay archived round-2 inputs without invoking models or changing historical records.

## Scope / rollback
Context projection, Runtime composition, production backend, matching schema/spec/tests only.
Rollback by reverting this repair commit. Preserve all delivery approvals and terminal journals.

# Planned milestones

1. Reproduce the exact public two-native-stops → attempt3 capacity → same-base PAUSE
   failure, preserving all original history and dirty files. Capture the red failure.
2. Independently review the additive proof design and ownership before production edits.
3. Add compatible binding/Schema evidence; validate exceptional same-base invariants in
   service, store and queue before mutation. Keep ordinary source-change behavior strict.
4. Pass the public integration regression through separate RESUME and independent verdicts;
   add targeted negatives, historical wire/hash and Schema regeneration checks.
5. Record the failure mode and existing-data instructions in core specs; review, commit and
   deploy only through parent's controlled service maintenance window.

# Current ownership

Agent blocked_context_recovery owns backend/domain/generator/schema and public integration
implementation in the task allowlist. capacity_failure_route owns the exact schema regression
and read-side engineering labels/tests; prior independent frontend changes are preserved.
Deployment/production approval remain root-owned. Never revert other agents' work.

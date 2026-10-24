# Maintenance implementation scope

The platform repair adds one target-free `rejected_candidate_rescue` capability.
It does not change the original K1 Product approval, Task/base, Coder permissions,
native rule baseline, old outcomes or independent verification requirements.

Implementation boundaries:

- Pure `RejectedCandidateOutputProof`: exact original unsupported successful report,
  original claim, complete owned-session stop and lawful clean committed candidate.
- Baseline models/service/store: exact plan/authority/binding associations, unchanged
  execution base, candidate-only source advance, full immutable patch and PAUSE.
- Queue: independently revalidate proof and original allocation while consuming one
  normal-work successor; separate exact continued-binding decision before dispatch.
- Expired-owner settlement: task process lock then queue authority/Task/claim locks,
  original snapshot plus real renewed lease, two complete current stop/candidate
  readings, immutable settlement record, and EXPIRED audit event. No rescheduling,
  outcome rewrite, WorkItem change or refund. This requires minimal additions to
  `work_queue/worker.py` to distinguish held Task-lock checking from Worker ownership.
- Adapter admission: an actually consumed latest binding and fresh real Coder claim
  can report the unchanged retained candidate after full original-base comparison;
  ordinary no-change reports remain rejected. The common inventory checker permits
  only bounded explicit regular 0644/0755 execution-cache changes.
- Console protocol 11: exact sealed plan supplies the specialized controls despite
  the old blocked projection; ordinary terminal recovery guards remain strict.
- Physical deletion: the new settlement namespace and full embedded ownership enter
  the existing verified resource inventory; removal does not leave orphan records.

Allowlist extension from the initial PRD is limited to `work_queue/worker.py`,
`multi_directory/purge_state.py`, the new typed owner record, their focused tests and
the exact executable specs/runbook. These are necessary resource-lifecycle fixes,
not additional K1 business scope.

Rollback point is the prospective version-admission maintenance commit
`358b0860fadd6a3a1159e97aa5f4f64d0b5a5109`. Before consuming any new binding, the
maintenance can be reverted at an idle boundary. After additive records exist,
retain compatible readers and forward-fix; never delete audit records or revive
the retired owner.

# Retired Console catalog scope correction

## Scope and authority

A fault-retirement plan's `scope` records the catalog selected by the maintenance
caller's `ASE_CONFIG`; a legacy Host did not durably record its own config. The
retirement, `REFUSED` result, original log, signal receipt and UNKNOWN execution
outcome remain immutable. A wrong caller catalog can be corrected only by a new,
explicit local engineering decision while the successor is in inspection mode.
This does not approve a Requirement, resume a Run, or establish that the old
Host's environment was directly observed.

New production Hosts include `config_path`, `platform_root`, and raw config
`config_sha256` together in `ServiceInstance`. Fault retirement prepare and
execute compare all three against the selected caller config before any signal.
Old instance records omit all three and retain their exact bytes.

## Signatures and records

`prepare_scope_correction(environment, operation_id, authority_reference)
-> MaintenanceScopeCorrectionPlan` seals an unapproved plan in the active
retirement archive. `execute_scope_correction(environment, plan_sha256,
confirm_scope_correction=True) -> MaintenanceScopeCorrection` appends the
decision. Both hold `console-service-replacement.lock`; the CLI accepts no
caller-supplied root, PID, log digest, queue count, or Operation body.

The plan binds current retirement plan/receipt/marker digests, local UID, the
wrong observed catalog root/config digest, the previous **completed and
normally admitted** epoch's marker and platform root, the target config/root,
Team manifest, terminal Operation ID/digest, its Project/Requirement IDs,
archived log SHA, and an external human authority reference. It explicitly
classifies the scope as `EVIDENCE_BASED_RUNTIME_SCOPE`, with historical outcome
`UNKNOWN` and Requirement action `NONE`. The decision binds that plan digest
and is written once. Both are private, typed, digest-checked JSON. A pending
plan without a decision blocks maintenance completion in every config.

## Evidence and gates

The target root must equal the previous admitted epoch's retirement scope.
The archived original log must still match the sealed retirement log SHA and
contain the exact `Console operation <ID> failed with ` line. The target Team
manifest, Project and Requirement directory and terminal Operation journal
must validate. The same Operation ID must be absent from the wrongly selected
catalog. A missing, changed, symlinked, or ambiguous witness refuses without
granting normal authority. The evidence supports an engineering assessment;
it does not prove the old process environment or settle its owned tools.

`MaintenanceCompletionPlan.scope_correction_sha256` binds the decision when
present. Completion preparation, explicit completion and first normal
admission freshly recheck the full evidence and still require a stopped
inspection successor plus the existing complete idle queue snapshot. Normal
startup validates the immutable correction chain. After first admission, each
subsequent normal launch must still use the corrected platform root and Team
identity. Other config settings may change through ordinary controlled apply;
the correction does not freeze their bytes forever.

| Input or failure | Required behavior |
| --- | --- |
| Legacy instance, exact prior admitted root and canonical log/Operation witness | Prepare immutable plan; still inspection |
| Exact plan digest, local UID and explicit `--confirm-scope-correction` | Append one decision, keep retired bytes unchanged |
| Pending plan without decision or unrelated current config | Refuse completion and normal admission |
| Changed archived log, target Operation or config before first admission | Refuse; no queue or Requirement mutation |
| Different `ASE_CONFIG` root or Team on a later normal launch | Refuse before writer composition |
| New instance with caller config path/root/raw SHA mismatch | Refuse fault retirement before any signal |
| No prior admitted epoch, missing witness or a forged plan digest | Refuse correction; remain inspection |

Good: exact previous admitted root, matching original failed Operation/log,
fresh idle queue, human reference and explicit confirmation allow a new normal
admission without altering the old retirement. Base: no correction leaves the
existing same-root completion path unchanged. Bad: no prior admitted epoch,
wrong target root, arbitrary log substring, wrong/missing Operation, pending
plan, changed log/journal/config, changed plan digest, already completed epoch
or later wrong-root launch must refuse.

Tests: `test_maintenance_scope_correction.py` exercises three real local
retirement epochs, durable Operation journal, pending and failed correction,
original-byte preservation, later config-root refusal and Schema parity.
`test_maintenance_completion.py` and `test_fault_retirement.py` retain their
legacy and normal-path checks.

No SQL row, Task, Operation, approval, QA/Review verdict, draft or old Run is
rewritten. Roll back only to a version that reads and enforces the correction
and completion records; never remove the inspection marker or decision to
force normal startup. If correction cannot be proven, keep inspection mode.

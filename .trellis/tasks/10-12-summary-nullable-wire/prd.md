# Accept canonical omitted nullable Task identity fields

Bug: DomainModel.to_wire omits None, while browser compares absent Task source identity
against explicit null. A valid legacy child or candidate verification rejects the entire summary.
Scope: app.js nullable identity comparisons; real Python wire-to-shipped-JS regression; UI spec.
Acceptance: omitted and null identity fields are equivalent only where the typed contract allows
absence. Legacy no-Task, candidate verification, current delivery and remediation summary/detail
all read correctly; nonempty identity/checkpoint/resource mismatches continue to reject.
Validation: pytest real to_wire fixture invokes shipped JS Node VM; relevant existing Node tests.
No database/record/schema change. Rollback code only, retaining all original facts.

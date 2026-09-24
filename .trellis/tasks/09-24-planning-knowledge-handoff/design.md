# Design

1. Add optional `RequestView.knowledge_wait_stage` from the validated JointCheckpoint and
   use it for wait labels/progress. No UI reconstruction from guesses or document titles.
2. Keep KnowledgeRunBinding.source_revision hashes immutable. Add a typed repository
   inspection context to new joint consultations: aggregate fingerprint plus unit/repository,
   actual read-only checkout path and Git revision. Version new consultation identity.
3. Preserve approved facts as authority; ordinary engineering choices and code inspection
   belong to Designer/Planner. Add explicit design blocking issues with bounded correction
   before committing a design, rather than parsing risk prose heuristically.
4. Add RECHECK_DESIGN to the existing Console operation pipeline. Only an exact, unresolved
   Design/Planning knowledge wait before child dispatch is eligible. Append a scoped recheck
   record and a DESIGNING successor retaining Product/approval and prior budget. Clear the
   current design/plan/decision, keeping old bytes in the journal; pass the old gap to new
   consultation as required recheck context. A new real human gap remains blocking.
5. Recheck is a change of investigation ownership, never a KnowledgeResolution or verdict.
   Existing gap views distinguish recheck from approved answers. Provider execution occurs
   only on a later ordinary Continue action.

## Alternatives

UI-only repair leaves the false human gate. Blindly accepting all repository-looking gap
text bypasses genuine decisions. Requiring another user approval of an invented icon changes
the request. Explicit bounded recheck preserves both product scope and failure history.

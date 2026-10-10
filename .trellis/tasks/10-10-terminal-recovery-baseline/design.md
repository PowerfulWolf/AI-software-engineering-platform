# Design

## Typed source references

`RecoverySource.base_revision` remains the original frozen approved Task base. Add paired optional
`execution_baseline_sha256` and `execution_base_revision`, omitted when absent. A computed
`effective_base_revision` returns the approved execution base or the original base for historical
sources. Every plan digest includes present references; no optional absent key changes old digests.

`NativeRecoverySourceReader` verifies the complete non-wire baseline lineage before returning
the exact optional references in `RecoverySource`. Read the chain only through
`FileExecutionBaselineStore(..., read_only=True).bindings_for_task(task_id)`: that validates stored
plans, starts, engineering authority, predecessor lineage and retained full Context. Recheck each
binding's exact Task intent/scope. The original invocation request and required execution-baseline
Context must select the same latest binding/base as the source reader.

## Event epochs

StateEvent revision is its contiguous SQL position. Each binding starts after its sealed
`prior_task_revision`; the latest applicable binding owns the source for a later event. The event
must occur after that binding completed and use at least its precise reserved execution attempt
from the sealed plan facts. A stale earlier source is rejected even if it appears somewhere in the
chain. Events before the first binding retain the original approved source. This is source
validation; existing state/dispatch/candidate gates remain mandatory.

## Capture consumers

Recovery proposal, scope discovery, requested-file metadata, plan lineage and current-target
ancestry use `effective_base_revision` for complete requirement edits. The original upstream
Product/Design/Plan/Task contracts continue to use frozen `base_revision`. This prevents source
updates already approved by engineering from becoming requirement edits or scope supplements.

## Good / Base / Bad

| Case | Expected result |
|---|---|
| Old events at frozen source, terminal event after exact verified latest binding | Accept epoch; bind latest digest and effective base |
| No baseline store, ordinary terminal history at original base | Existing source/wire/SHA behavior |
| New source without binding or source from an earlier binding | Reject |
| Event before binding completion or reserved attempt | Reject |
| Wrong scope/Task/predecessor or altered plan/authority/full Context | Reject |
| Only one new wire reference supplied | Reject |
| Old frozen base used to capture a bound recovery | Reject plan lineage |
| Current source has ignored unauthorized mutations | This change provides no stop/inventory admission; separate exact containment gate required |

## Validation seams

Use a pure typed epoch validator with small Task/StateEvent/Binding fixtures, real immutable
baseline-store fixtures for reader tests, wire/hash tests for historical and bound plans, and
read-only MySQL fixtures only where the formal source-reader composition needs them.
Do not run the full suite or invoke real models.

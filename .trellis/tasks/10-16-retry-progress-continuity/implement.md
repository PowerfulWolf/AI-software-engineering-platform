# Diagnosis and implementation record

The read-only production trace establishes a concrete symptom: accepted step01 progress
exists on source774e0a6, but the next stopped-failure retry request has completed_step_ids=[]
and selected01/02. The initial candidate causes were baseline construction retirement,
resolver input selection, and work-slice selection. Exact immutable binding1 explicitly
retires the accepted artifact; binding2 null correctly does not undo that historical act.
The resolver and work-slice are therefore following the existing history, not dropping an
eligible artifact independently. The fix belongs at new binding construction.

Worker responsibility: produce a RED service/binding-to-request regression, then preserve
accepted progress only for new STOPPED_FAILURE_RETRY bindings. Root documents the contract;
independent reviewers validate the final code/negative cases before submission. Existing
bindings retain all original digests and interpretation. The active native01/02 slice can
establish a new accepted successor, subject to its actual output and normal validation.

Production observations and exact test/review results are recorded after they occur.

# Design

ProductionConfig.design_retry_policy → TeamHost/JointDeliveryService and ProductionTeamReader →
RequestView.design_budget → UI action/guidance. Policy changes require the existing settings restart.
Both consumers use the same typed policy/defaults and derived budget model.

Design reserves `attempts.design` before `_produce`, preserving crash safety. A retryable
StructuredModelError appends one checkpoint decrementing that reservation and incrementing
`attempts.design_transient`; it rethrows the original typed error for provider diagnostics.
Successful/invalid output does not reset the transient count. A KnowledgeGap still refunds the
artifact reservation without spending transient allowance. Corrections retain original feedback.

Existing RecoverDesign keeps its historical approved KnowledgeResolution/exact checkpoint gate;
it resets only Design attempts. It must not bypass an exhausted transient budget. Operators can
increase either finite limit in Settings and restart; lowering a limit never erases spent counts.
Legacy journals retain their original shared-count meaning until an explicit recovery. New default
fields are added only to config/projection, not immutable checkpoint payloads.

UI order: active operation; eligible recovery; exhausted-budget guidance; ordinary failed Design
retry. Do not label every exhaustion as a knowledge accounting error.

Rollback: revert the code commit and remove `design_retry_policy` from configuration before running
the old strict parser. Keep all journal records; old code ignores the additional attempts key but
will resume its old shared-budget behavior, so suspend Design continuation during rollback.

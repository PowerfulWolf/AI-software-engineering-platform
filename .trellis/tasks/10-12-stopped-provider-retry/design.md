# Minimal typed contract

`StoppedProviderFailureProof` contains the immutable `DeliveryInvocationOutcome`,
`ExecutionCaptureStart`, `ExecutionCaptureStop` and proof digest. Its model
accepts only Coder FAILED AUTHENTICATION_ERROR, nontransient and no artifact;
the full request and historical claim/start/stop must match. It does not record
a health assertion or grant execution authority. Existing complete-draft capture
validation is factored into a shared typed function used by both completed-output
and stopped-provider proofs; neither weakens the other's failure semantics.

`BaselineExecutionFacts.stopped_provider_failure` and reservation cause
`provider_prerequisite_repaired` bind exact original start/outcome/proof and
consume ordinary work. The collector freshly calls `validate_capture_stop`
under the real Task lock and idle SQL fence, rejects accepted publication and
receipt mixing, then rechecks the same proof immediately before SQL consumption.

`BaselinePurpose.STOPPED_PROVIDER_RETRY` omits target in the public proposal and
derives the current trusted execution base in collector and service. Its plan
requires preserve_draft, same source/base, unchanged dirty patch, no native-rule
change/conflict or accepted implementation. Source rebind uses a different
explicit target and may carry the same proof; it keeps existing full capture,
rebase preview, native-rule review and approved coder_reapply contracts.

Both purposes with this proof require a human `BaselineOperatorAuthorization`,
`confirm_provider_prerequisites_repaired=True`, and PAUSE. Confirmation names the
original provider/native prerequisite error; it is not automatic provider-health
validation and cannot accept a role verdict. Binding carries optional
`stopped_provider_failure_sha256` (absent when unused), and reopening verifies
the exact proof/authority. Queue consumption requires a distinct successor and
ordinary accounting; latest-bound explicit RESUME uses existing services.

No DeliveryWait resolution or transient error enum is broadened. Console UI
selects the general typed preparation purpose and expresses failure, preservation,
explicit prerequisite confirmation and normal work cost. Old handling remains
history; frontend capability/version and exact callback gates are Root's scope.

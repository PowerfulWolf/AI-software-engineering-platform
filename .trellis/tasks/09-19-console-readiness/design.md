# Design

Authority: /api/v1/console for delivery readiness; Settings restart_required for saved-vs-process
configuration; /admin/status for dependency details. Configuration lifecycle SUCCEEDED is a completed
operation, never proof of delivery readiness and never a new event on ordinary navigation.

Separate lightweight Console/Settings refresh from the Project Team projection. Preserve the editable
draft during background reads. Query dependencies on explicit Status entry/refresh or on confirmed
apply/readiness transition; do not probe MySQL on every Team poll. Retain false/unknown distinctions.

Success feedback has a bounded UI lifetime and acknowledgement; historical terminal state does not
restart that lifetime. Existing durable lifecycle history remains unchanged.

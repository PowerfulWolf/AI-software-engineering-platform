# Keep verified Team reading identity through Console interruptions

Goal: prevent a transient Console metadata failure from poisoning subsequent valid Team summary reads.
Scope: app.js, focused Node regressions and Team summary UI spec. Keep current write authority separate from last successfully negotiated read identity; preserve exact Team/checkpoint checks and distinguish current maintenance mode from last confirmed maintenance mode.
Acceptance: normal and inspection successful refresh -> Console failure -> same-Team summary remains readable with zero POST; successful reconnect restores only freshly verified controls; initial failures, 404, Team/version changes, mismatched scope and metadata are handled explicitly. No production requests, database writes, service actions or K1 delivery.
Validation: RED/GREEN real shipped refresh HTTP chain, related summary/readiness/capability tests and canonical Python wire regression. Incremental tests only.
Allowed paths: src/ai_software_engineer/team_view/app.js; tests/team_view/*reading*.test.cjs and related fixture; .trellis/spec/core/team-summary-detail-ui.md; this task directory.
Rollback point: 509f25435162ccb4e15efb6dddcfb88ea06fdd12. Roll back client changes; no persisted state migration or approval changes.

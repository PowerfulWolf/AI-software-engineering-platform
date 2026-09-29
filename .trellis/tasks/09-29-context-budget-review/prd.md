# Delivery context budget and frozen handoff review

## Goal and scope

Keep all approved Product/Design/Plan/approval and role-required Artifact payloads in
delivery Context. Preserve frozen native-rule bytes for knowledge search/read and
existing gap resolution lineage. Compact only the production prompt projection when
active knowledge consultation is present. Retain all AGENTS.md bodies, including
nested instructions. Timeout policy and live delivery restart are out of scope.

Increase the shared production delivery/independent verification input estimate from
64,000 to 128,000 tokens; retain the 4,000 output accounting reserve. Local Codex model
metadata fetched 2026-09-28 reports 272,000 context_window and 95% effective window for
the configured gpt-5.6-sol/gpt-6-sol/gpt-6-astra routes. Official documentation could not
be fetched (DNS unavailable). This is a bounded initial-input policy, not a provider
capacity guarantee or a change to provider output/thinking limits. The existing
characters/4 estimator is approximate; required sources still fail closed on overflow.

## Allowed changes

Context projection helper, production delivery composition and shared budget,
focused Context/knowledge/delivery/recovery tests, and related architecture/spec docs.
Preserve concurrent timeout changes and all historical facts.

## Acceptance and verification

- Original native source IDs, contents, scopes and retrieval snapshot hashes survive.
- Search/read finds body-only terms and returns exact cited frozen text.
- Old approved knowledge resolution is included after reopening stores with the new
  prompt projection; old snapshots and receipts are unchanged.
- Coder -> QA -> Reviewer, Coder progress and rework retain complete upstream payloads.
- Task, profile, baseline, knowledge receipt and required joint artifacts coexist.
- An input between 64k and 128k is accepted; required input above 128k is rejected.
- Ruff, strict mypy and focused pytest Context/knowledge/delivery/verification suites.

## Existing data and rollback

No SQL/journal/artifact migration or automatic reopening of terminal Tasks. The K1
Task blocked before its first Coder Run lacks the Run/Context required by the current
terminal recovery seam; keep it paused pending an audited successor recovery entry.
Before production resumes, revert only this task's changes to roll back. Historical
immutable facts remain readable; contexts exceeding the restored 64k limit cannot be
regenerated under the old policy. Once compact Contexts with knowledge.reads have
produced live Artifacts, retain the new gate or roll forward: the old binary rejects
that new section layout. Never rewrite Context/Artifact history to downgrade.

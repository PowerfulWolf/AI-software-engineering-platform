# Conditional Python source-binding reporting

Goal: clarify native Coder tooling instructions so a successful source-binding inspection is
reported from the actual command result; NOT_RUN is required only for an unexecuted check,
missing safe tools or an actual launcher source-shadow refusal.

Evidence: accepted K1 progress art_coder_05714ae8093596356e007b54dc42490b reports the
source-binding prerequisite NOT_RUN "per execution contract" while separately describing
current-worktree import inspection. The generic tooling prompt currently orders that status
after a paragraph about possible shadow refusal, without making the reporting condition explicit.
This establishes ambiguous guidance, not independently proven bad source binding or a business
test defect. Historical artifact/evidence/status remains unchanged.

Allowed paths: src/ai_software_engineer/agents/codex_cli.py (only tooling prompt helper),
.trellis/spec/core/production-team-host.md (existing tooling contract), this task directory.
Existing tests/agents/test_native_python_tooling.py may be read and run; add no tests that merely
mirror prose. No launcher/bootstrap, permission, environment, schema, state or recovery changes.

Acceptance: successful commands keep truthful outcomes; actual refusal and unavailable tooling
remain NOT_RUN with no install/repair authority or candidate PASS; independent QA/Review stays
mandatory. Run the existing focused registered-tool/current-source and unsafe-tool prompt cases,
Ruff/format, targeted mypy and diff check. Independent read-only review before merge.

Deploy only at the pending safe idle boundary with the prior progress-continuity patch. Old K1
NOT_RUN/FAIL entries remain immutable and need new actual verification before candidate acceptance.
Rollback: revert this prose-only change after a controlled stop; keep all durable records.

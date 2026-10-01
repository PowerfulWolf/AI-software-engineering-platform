# Bugfix batch pre-commit verification — 2026-10-01

Base: `d87f0bb`. The batch includes CLI diagnostic classification, accepted-progress
recovery, expired-lease recovery, exact requested scope and Coder knowledge-wait/UI fixes.
The separate Python/MySQL foundation remains unregistered in production.

## Checks and independent review

- `pytest -q tests/agents/test_structured_models.py tests/recovery/test_models.py
  tests/recovery/test_progress_source.py tests/recovery/test_interruption_records.py
  tests/recovery/test_knowledge_wait.py tests/recovery/test_scope.py
  tests/web_console/test_scope_contract.py tests/web_console/test_manager.py -m 'not mysql'`:
  140 passed in 7.97s.
- `node --test tests/team_view/delivery-status.test.cjs tests/team_view/ui.test.cjs`:
  16 passed.
- `pytest -q tests/team_view/test_live.py -k 'current_queue_wait_overrides or active_child_task'`:
  4 passed, 26 deselected.
- Ruff check, Ruff format check and Mypy on all 41 changed Python files passed.
  The final test-only type annotations were followed by `pytest -q
  tests/recovery/test_knowledge_wait.py`: 15 passed in 0.60s.
- Independent QA `/root/recovery_qa` repeated 84 focused tests (1.28s), verified
  the schema and current-wait findings were closed, and found no blocking issue.
- Independent Reviewer `/root/recovery_review` found no new blocking issue and
  confirmed Git clone/worktree isolation. Existing native Git/MySQL results and
  real Chrome evidence remain recorded in the individual implementation notes.
- No full test suite was run. No long MySQL suite was repeated for submission.

## Existing-data handling

The current K1 gap was adopted and answered through native APIs with immutable resolution
`99f124131c5036ee6b88875c4274d9a76a170607f3591a66bdeb37df3313da75` and HumanAction audit.
No direct SQL change, Task reset, budget refund, permission overwrite or historical deletion
was used. Operation `operation_51c3c831bd4e4bf3e6b0582d7004efad` continues the same Task.
At 10:08:35Z, the fifth Coder progress was accepted and the next attempt started.
This is a non-candidate checkpoint, not an independent QA/Review verdict.

The business clone and K1 worktree both retain `acc5f37`; the platform development checkout
is a separate Git repository. Push does not update a frozen Task. Five paths overlap with
this bugfix batch and `web_console/administration.py` also overlaps earlier platform commits.
Keep a running Coder untouched. At a supported recovery checkpoint, fast-forward the clean
business clone to an exact published SHA, prepare a new target and approve the exact scope
and recovery plan. If the full patch conflicts, approve a new `coder_reapply` plan for the
native Coder to adapt, then require independent QA/Review. Never rebase an active worktree
or reinterpret an old approval as authorizing a different base.

## Limits and rollback

K1 still needs the exact schema-fixture path authorization and isolated MySQL verification.
The terminal-only scope entry does not authorize a nonterminal successor. Foundation fixture
passes do not establish production verification capability or candidate acceptance.

Rollback requires reverting the relevant code commits and restarting only after active
operations stop. Preserve journals, approvals, HumanAction events, progress, receipts and
worktrees; do not downgrade or rewrite persisted facts to match older code.

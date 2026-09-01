# T008 Verification

## Acceptance evidence

- `tests/agents/test_fake.py` covers role-compatible success artifacts, role/output-Schema mapping, QA FAIL, Reviewer REJECT, timeout, invalid/provider failures, scenario routing, missing/invalid configuration, artifact task/role/run/kind/revision/context mismatch, immutable request/result invariants, exact replay and run conflicts.
- `src/ai_software_engineer/agents/` exposes one typed `AgentAdapter` seam for Fake and future provider adapters; no network, Git, filesystem, or SDK access is present.
- `docs/prompt-protocol.md`, `docs/contracts.md`, `docs/architecture.md`, and `.trellis/spec/core/python-runtime.md` record request/result fields, failure codes, role boundaries, and test assertions.

## Quality gates

| Check | Result |
|---|---|
| `uv run pytest` | 173 passed |
| `uv run ruff format --check .` | passed |
| `uv run ruff check .` | passed |
| `uv run mypy src tests` | passed; 54 files |
| `uv lock --check` | passed |
| `uv build` | source distribution and wheel built |
| `git diff --check` | passed |

## Safety note

Successful results are accepted only when Artifact task, producer role/run ID, kind, source revision, and context manifest match the request. Timeout, provider error, and invalid output results never carry an Artifact or verdict. Exact `run_id` replay is idempotent; a changed request for an existing run raises `AgentRequestConflict`.

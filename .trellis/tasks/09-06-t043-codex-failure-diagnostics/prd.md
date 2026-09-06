# T043 Preserve safe Codex failure diagnostics

## Goal and scope
Round3 Coder exited unsuccessfully with a dirty worktree after 580,616ms. The adapter discarded
underlying classification and process output, leaving only a generic policy failure. Repair that
diagnostic loss, not the feature or historical results. The original provider reason is unknown.

## Acceptance
- Failed/interrupted execution keeps non-transient POLICY_VIOLATION when Git effects exist;
  no fallback, cleanup, candidate, fake verdict, retry reset or terminal resurrection.
- Failure messages carry safe known category (or UNKNOWN_EXIT), return code and SHA-256 of captured
  stdout/stderr, never raw output/credentials/task prose. Existing AgentResult wire is unchanged.
- Bounded capture retains beginning and end so long execution logs do not hide trailing errors.
- Timeout capture preserves bounded partial output only for safe diagnostics.
- Offline real-Git tests prove root classification survives dirty rejection, clean routing is unchanged,
  unknown failures are explicit, secrets are absent and captured-tail classification works.
- Full tests/lint/types/build; no live model calls. Revert this isolated commit to roll back.

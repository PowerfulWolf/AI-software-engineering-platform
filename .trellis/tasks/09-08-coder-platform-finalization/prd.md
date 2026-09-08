# Platform-owned Coder candidate finalization

## Evidence

Real recovery run `run_d90f0c10a0c34dc4852a659c618df06d` returned normally after producing
the complete authorized source/test/spec/documentation diff, but no candidate commit. macOS sandbox
logs record four denied attempts to create the linked-worktree `index.lock`: the role worktree is
writable while its Git metadata remains under the target repository outside the Codex sandbox.

## Acceptance

- Coder may return a provisional implementation report when Git metadata is sandbox-external.
- The platform validates the unchanged HEAD, exact reported/observed path set and every write path
  before staging anything.
- Only after validation, the platform creates one hook-free, non-interactive candidate commit and
  binds the final implementation report to its exact SHA.
- Existing model-created clean commits remain supported.
- Provider failure, timeout, partial/unauthorized changes and mixed commit-plus-dirty states remain
  blocked and preserved.
- QA and Reviewer still receive only the exact finalized candidate revision.

## Non-goals

Do not expose the target repository `.git` directory to the Agent, merge, push, deploy, accept a
dirty timeout/failure, weaken path policy, or change Task/verdict/retry schemas.

# Live Artifact version admission before candidate effects

Goal: reject unsupported Artifact schema versions before a platform candidate commit or a fresh SUCCEEDED outcome/publication, preserving immutable historical records.

Allowed maintenance paths: domain/artifact.py, artifacts/store.py, agents/{models,json_schema,codex_cli,responses}.py, directly related adapter/orchestration tests and this task/spec documentation. K1 source, worktree and durable facts are read-only.

Acceptance: all four role transport schemas bind v0.1; Codex and Responses dirty provisional v1.0/v0.2 reports leave HEAD/index and draft unchanged; generic live/replayed results become typed nontransient INVALID_OUTPUT before publication; historical SUCCEEDED bytes remain decodable and unchanged; ordinary valid candidates/progress continue. Existing RetryingOrchestrator failure control persists the policy-selected WAITING_DEPENDENCY investigation record and releases the role lease for INVALID_OUTPUT.

Rollback: revert this maintenance commit before any new recovery consumption; retain all historical outcomes. No DDL or production SQL changes.

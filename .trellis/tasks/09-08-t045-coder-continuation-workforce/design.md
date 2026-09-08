# Design

## Decision

Use explicit durable Task checkpoints for the user-visible continuation lifecycle while preserving
the existing orthogonal WorkItem scheduler state. `CONTINUE_REQUIRED` means a validated
`coder-progress` Artifact exists; `QUEUED` means no Coder is executing and the next bounded run may
be scheduled. Neither state is a candidate and neither can enter QA directly.

The final Git mutation belongs to `CandidateCommitSkill`, not the model adapter. The adapter parses
and normalizes provider output, then invokes the injected Skill only for an implementation report.
The Skill receives typed facts and has no Task/artifact/verdict authority.

Organization roster construction becomes one deterministic module used by both Host bootstrap and
dispatch. Host bootstrap publishes all seven model-agent profiles and the model policy before any
project request. Dispatch consumes those immutable records. Deterministic control components are
not added to the roster.

## Data flow

```text
Coder run
  ├─ implementation-report draft → CandidateCommitSkill → candidate SHA → QA
  └─ coder-progress → ArtifactStore
                       → CONTINUE_REQUIRED
                       → QUEUED
                       → next Coder run with exact checkpoint + dirty-path admission
```

## Validation matrix

| Case | Required result |
|---|---|
| Progress matches clean or exact authorized dirty worktree | seal checkpoint and queue continuation |
| Progress changed path differs from worktree | policy failure; no continuation |
| Candidate draft base/report/path mismatch | CandidateCommitSkill rejects; no commit |
| Crash after progress put but before state event | replay finds latest progress and completes queue edges |
| Crash at CONTINUE_REQUIRED or QUEUED | replay resumes from exact persisted checkpoint |
| Continuation budget exhausted | terminal BLOCKED with progress Artifact referenced |
| Existing candidate commit is clean and valid | no platform commit; existing validation path remains |
| Organization roster replay | exact records returned; changed same-version record conflicts |

## Rollback

Revert T045 code/schema/spec changes. Existing v0.1 Task rows do not use the new enum values and
remain readable. New tasks stopped in continuation states require T045 code to resume and must not be
silently interpreted by an older binary.

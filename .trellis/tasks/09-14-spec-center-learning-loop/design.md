# Spec center and learning loop design

## Domain boundaries

```text
Knowledge (descriptive)            Specs (mandatory)                 Learning (proposal)
business/project background        Team / Project / repo-native      QA FAIL / Review REJECT
read-only context                   versioned + scoped + verified      evidence + human decision
        |                                      |                              |
        +----------------------+---------------+                              |
                               v                                              |
                    Requirement preparation                                  |
                    exact immutable lineage                                   |
                               |                                              |
                 Coder -> QA -> Reviewer -------------------------------------+
                                                                  explicit collect
                                                                         |
                                                      approve Knowledge / Spec / Skill design
```

Knowledge never becomes enforceable merely because it was selected. Specs never become active merely
because a file was uploaded. Learning never changes organizational memory without human approval.

## Spec record

An immutable Spec version contains:

- logical `spec_key` and monotonically increasing `version`;
- Team or Project owner identity;
- title and canonical Markdown body;
- applicable roles and delivery stages;
- optional repository IDs and path globs;
- verification instructions;
- source/body hashes, record ID and manifest hash.

Each scope owns `specs/activation.json`, which maps every active logical key to one exact Spec ID.
Publishing another version does not activate it. Activation validates ownership and one-version-per-key
before one atomic write.

```text
<platform_root>/team/specs/
├── documents/<spec_id>/spec.json
└── activation.json

<platform_root>/projects/<project_id>/specs/
├── documents/<spec_id>/spec.json
├── activation.json
└── learning/<proposal_id>/{proposal.json,authorization.json?,decision.json?}
```

## Rule compilation and routing

- Active Team Specs are converted to `SpecRule(layer=PLATFORM_ENGINEERING)`.
- Active Project Specs are converted to `SpecRule(layer=PROJECT)` with an exact sidecar source URI and
  digest authorized by the production Project rule provider.
- Repository-native rules remain `SpecRule(layer=PROJECT)` with their discovered repository URI/hash.
- The compiler compares rules sharing the same `(scope, field)` key. Different values are conflicts;
  layer or priority only controls stable ordering and never chooses a winner.
- Role/stage/repository/path applicability is embedded in the rule value and kept in the baseline.
  Context routing continues to distribute the sealed baseline to Product, Designer, Planner, Coder,
  QA and Reviewer through existing typed bundles.

The TeamHost runtime cache key includes exact Knowledge and Spec records. Live administration invalidates
future runtime composition; an existing prepared operation still fails closed on lineage drift.

## Learning lifecycle

```text
QA FAIL / Review REJECT Artifact
  -> POST collect (explicit, idempotent)
  -> PENDING LearningProposal with exact artifact evidence
  -> human chooses target + approves or rejects
  -> persist immutable exact authorization before publication
  -> Knowledge: immutable Project document + selection update
     Spec: immutable Project Spec version + activation update
     Skill: immutable approved skill-design proposal only
  -> future Requirement preparation sees the new active version
```

The collector is deterministic. It does not ask a model to invent policy. It turns findings into a
structured draft containing the observed failure, source Artifact, proposed prevention rule and
verification evidence. A proposal ID is derived from its source Artifact/finding/target content, so
repeated collection does not create duplicates.

Publication is a recoverable two-phase boundary. An exact human authorization is written first;
Knowledge/Spec/Skill-design publication is idempotent; a final decision then records the published
URI. If the process stops between those writes, the Console exposes the pending authorization and
only allows the same authorized action to continue.

## Failure behavior

- Invalid/tampered Spec records fail before activation or preparation.
- Unknown repository scopes and unsafe path globs fail validation.
- Conflicting active Team/Project/repository rules stop at `WAITING_HUMAN`.
- A stale Learning decision, duplicate decision or changed proposal digest fails closed.
- Publishing Knowledge/Spec is preceded by exact authorization; a failed publication leaves a
  retryable authorized state and never records a false completion decision.
- Existing approved Requirements are not rewritten after any activation change.

## API/UI shape

- Add Team and current-Project Spec APIs for list/create/activate.
- Add current-Project Learning APIs for list/collect/approve/reject.
- The Console knowledge area gains top-level `背景知识`, `开发规范` and `学习建议` modes, retaining
  Team/Project scope selection where meaningful.
- Spec cards show key/version/status/applicability/verification. Learning cards show evidence,
  proposed target and decision state.

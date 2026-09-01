# AI Software Engineering Context

This context defines the shared language for auditable software delivery performed by constrained AI roles. These terms are organization-owned and remain stable even when an individual model or Agent implementation changes.

## Language

**Task**:
A bounded unit of requested software work tied to one repository, one base revision, explicit acceptance criteria, and a delivery state.
_Avoid_: Job, ticket, prompt

**Acceptance Criterion**:
A uniquely identified, independently verifiable condition that a Task must satisfy.
_Avoid_: Requirement item, checklist entry

**Agent**:
A long-lived, organization-owned team member with stable identity, capabilities, role eligibility, capacity, and performance history. An Agent is not owned by a Project and is not a model process.
_Avoid_: Project agent, bot, model instance

**Agent Profile**:
The versioned organization record describing one Agent's capabilities, eligible roles, capacity, trust, and default Model Policy. It does not contain project-specific permissions or a concrete model selection.
_Avoid_: Agent Definition, role config

**Role Assignment**:
A temporary, auditable binding of one Agent to one Role for one Task attempt. Assignment does not transfer ownership of the Agent to the Project.
_Avoid_: Project agent, permanent role

**Task Lease**:
An expiring claim on an Agent's bounded capacity for one Role Assignment. Releasing or expiring a Lease makes the Agent available without discarding Task evidence.
_Avoid_: Lock, ownership

**Work Item**:
The schedulable representation of a Task, carrying priority, required capabilities, risk, availability, and waiting state independently from delivery status.
_Avoid_: Task status, queue message

**Project Profile**:
An immutable, integrity-checked observation of one project's language markers, build systems, VCS revision, and project-native rule sources. It records facts and URI/hash references; it does not guess test commands or interpret Markdown semantics.
_Avoid_: Generated project policy, Agent memory

**Compiled Spec**:
The deterministic set of explicit structured organization, project, and Task rules admitted for one project delivery after conflict checks. It is injected into Context as one required, hash-addressed source.
_Avoid_: Prompt prose, merged Markdown

**Spec Conflict**:
An immutable record that two or more applicable structured rules cannot be safely combined. Engineering conflicts route the Work Item to `WAITING_HUMAN`; hard safety rules cannot be relaxed.
_Avoid_: Warning, Agent choice

**Spec Resolution**:
An evidence-backed human decision that resolves or terminates one Spec Conflict without rewriting its history.
_Avoid_: Chat approval, silent priority override

**Organization Workspace**:
The external durable root owned by the AI engineering organization for Agent Profiles, Model Policies, Work Items, Leases, and metrics. It never lives inside or belongs to a target project.
_Avoid_: Project workspace, source checkout

**Runtime Workspace Binding**:
The integrity-checked composition fact connecting one Organization Workspace, one Project sidecar, one Project Profile, fixed Runtime paths, and the exact target project root.
_Avoid_: Current working directory, CLI defaults

**Model Policy**:
An organization-owned rule set that defines eligible models, a default Brain Tier, risk floors, and escalation signals for Agent Runs.
_Avoid_: Agent model, provider config

**Run Demand**:
The objective, run-scoped routing facts derived from a Task, Context, Artifact, and event history: role, risk, context size, planned change scope, affected layers, failure counts, and critical-path impact. It is input to ModelRouter, not an Agent's self-reported confidence.
_Avoid_: model guess, confidence score

**Model Selection**:
The concrete provider, model, Brain Tier, policy version, and reasons allocated to one Agent Run.
_Avoid_: Agent brain, default model

**Agent Run**:
One isolated invocation for a Role Assignment, identified by a `run_id` and bound to one Agent, Model Selection, Context Manifest, tool policy, source revision, and Task attempt.
_Avoid_: Session, conversation

**Task Attempt**:
One Coder-to-QA-to-Reviewer delivery cycle for a Task. A retry starts a new Task Attempt and preserves the previous evidence.
_Avoid_: Retry loop, rerun

**Artifact**:
An immutable, schema-validated record produced by one Agent Run and persisted for downstream decisions.
_Avoid_: Message, response, output blob

**Candidate Revision**:
The exact Git commit proposed for QA, review, and eventual human delivery.
_Avoid_: Latest code, current branch

**Context Manifest**:
The deterministic, role-scoped inventory of redacted sources, hashes, machine policy, exact source revision, and token budget supplied to one Agent Run. Prompt-template versioning is a later extension; v0.1 does not infer sources from implicit conversation memory.
_Avoid_: Prompt context, memory dump

**Evidence**:
A stable, locatable reference to a command result, test, diff, file, log, or metric that supports an Artifact claim.
_Avoid_: Explanation, confidence

**Evidence Record**:
An immutable, redacted, SHA-256 sealed fact captured for one Agent Run, discriminated by command, diff, test, or Agent usage and bound to the run identity.
_Avoid_: Raw provider response, unverified log

**Run Evidence Manifest**:
The sealed, ordered index of every Evidence Record for one run, including outcome, identity and time window. It is the replay boundary for a run and cannot be edited in place.
_Avoid_: Run transcript, verdict

**Typed Tool Request/Result**:
A schema-validated operation envelope (`read_file`, `write_file`, or tokenized `run_command`) and its success or fail-closed rejection. It is bound to a role, run and operation ID; it is not a shell API.
_Avoid_: Tool text, ambient command

**Policy-Bound Tool Registry**:
The application service that authorizes typed tool requests against one role worktree and returns typed results without exposing filesystem, subprocess, artifact, verdict or state-store handles.
_Avoid_: Agent sandbox shortcut

**Finding**:
A structured, severity-rated issue linked to Evidence and returned by QA or Reviewer.
_Avoid_: Comment, opinion

**Verdict**:
An independent QA `PASS`/`FAIL` or Reviewer `APPROVE`/`REJECT` decision for one Candidate Revision.
_Avoid_: Self-assessment, looks good

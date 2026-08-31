# AI Software Engineering Context

This context defines the shared language for auditable software delivery performed by constrained AI roles. These terms are organization-owned and remain stable even when an individual model or Agent implementation changes.

## Language

**Task**:
A bounded unit of requested software work tied to one repository, one base revision, explicit acceptance criteria, and a delivery state.
_Avoid_: Job, ticket, prompt

**Acceptance Criterion**:
A uniquely identified, independently verifiable condition that a Task must satisfy.
_Avoid_: Requirement item, checklist entry

**Agent Definition**:
The versioned role, model, permissions, artifact contract, retry limit, and execution budget used to configure Agent Runs.
_Avoid_: Agent config, bot

**Agent Run**:
One isolated invocation of an Agent Definition for a Task attempt, identified by a `run_id` and bound to one Context Manifest and source revision.
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

**Finding**:
A structured, severity-rated issue linked to Evidence and returned by QA or Reviewer.
_Avoid_: Comment, opinion

**Verdict**:
An independent QA `PASS`/`FAIL` or Reviewer `APPROVE`/`REJECT` decision for one Candidate Revision.
_Avoid_: Self-assessment, looks good

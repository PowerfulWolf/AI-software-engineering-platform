# AI Software Engineering Context

This context defines the shared language for auditable software delivery performed by constrained AI roles. These terms are Team-owned and remain stable even when an individual model or Agent implementation changes.

## Language

**Team**:
A long-lived AI software engineering unit that owns its Agents, model policies, capacity and reusable Team Knowledge while serving one or more Projects.
_Avoid_: Company, tenant, code repository

**Team Workspace**:
The external workspace holding the platform's one Team, its members, policies, Team Knowledge, Team Specs and Skills. It is a sibling of the Project catalog and is never stored inside a target code repository.
_Avoid_: Company Sidecar, Project workspace, source checkout

**Team Knowledge**:
Reusable knowledge that applies across the Team's Projects and is explicitly selected during context compilation.
_Avoid_: Company knowledge, universal prompt, implicit Agent memory

**Project**:
A stable product or business context served by the Team. It owns Project Knowledge, Project Specs, a Repository catalog and its Requirements; it is not synonymous with one code repository.
_Avoid_: Team, Requirement Project, code checkout

**Project Knowledge**:
A Project-scoped collection of domain facts, architecture knowledge, native-rule references and historical decisions reused by relevant Requirements.
_Avoid_: Project Knowledge Module, code clone, Requirement evidence

**Requirement**:
One user objective within a Project. It owns product discovery, technical design, execution planning, Tasks, Artifacts, Evidence, recovery and delivery facts, and may select several Repositories or directory scopes.
_Avoid_: Requirement Project, code repository, Project, single-repository Task

**Repository**:
A stable code resource registered beneath one Project and described by an integrity-checked Repository Profile. A Requirement references one or more Repositories and narrows each to an allowed directory scope.
_Avoid_: Project, Requirement, transient worktree

**Requirement Request**:
A durable request tied to one Requirement, containing evolving user intent before it is specific enough to become delivery Tasks.
_Avoid_: Project Request, raw prompt, Task, chat session

**Requirement Preparation**:
The deterministic pre-conversation checkpoint proving that the Requirement's selected Repositories, directory scopes, Repository Profiles and applicable Team/Project/native rules are bound and conflict-free.
_Avoid_: Project Preparation, requirement discussion, Task planning

**Manager**:
The Team-owned Agent that leads the Team, accepts work, communicates with the user, advances stages, coordinates specialist Agents and delivers results. Its privileged actions are exposed as policy-bound Skills backed by deterministic application services; the Agent cannot bypass their validation or stores.
_Avoid_: Project Manager, super-agent, autonomous judge, Scheduler

**Agent Skill**:
A typed, policy-bound capability an Agent may invoke for its role. A Skill delegates authoritative work to deterministic services and returns verifiable results; it is not prompt prose and does not grant ambient access to stores, state, or subprocesses.
_Avoid_: Prompt instruction, hidden authority, arbitrary tool call

**Product Agent**:
A Team-owned Agent eligible for the Product Role, responsible for clarifying user intent and producing a reviewable Product Spec.
_Avoid_: Producter Agent, Task creator, requirements chatbot

**Product Spec**:
An immutable, versioned product definition containing goals, non-goals, requirements, acceptance criteria, assumptions, open questions, and traceable user decisions for one Project Request.
_Avoid_: Prompt summary, Task description, informal PRD

**Designer Agent**:
A Team-owned Agent eligible for the Designer Role, responsible for turning a frozen Product Spec and verified Project facts into a Technical Design. It is a technical solution role, not a UI/UX visual-design role.
_Avoid_: UI designer, Coder, planning-mode Orchestrator

**Technical Design**:
An immutable, versioned implementation contract mapping Product Spec requirements to architecture changes, implementation steps, test strategy, risks, and verification points.
_Avoid_: Coding notes, Product Spec, unstructured plan

**Planner Agent**:
A Team-owned Agent eligible for the Planner Role, responsible for producing an Execution Plan from verified product, design, Project and Team facts. It may use read-only Scheduler/ModelRouter preview Skills to test feasibility, but it cannot commit concrete Agents, models, Assignments, or Leases.
_Avoid_: Manager Service, Scheduler, super-agent

**Dispatch Commit**:
The Manager Agent's policy-bound action that revalidates an approved Execution Plan through the deterministic Scheduler and ModelRouter, persists Role Assignments, Leases, and Model Selections, and only then starts eligible Agent Runs.
_Avoid_: Planner suggestion, self-assignment, prompt routing

**Execution Plan**:
An immutable plan describing delivery phases, checkpoints, required roles and capabilities, risk signals, and model-tier demand without containing a concrete Role Assignment, Lease, provider, or model selection.
_Avoid_: Assignment, Model Selection, mutable schedule

**Task**:
A bounded unit of requested software work tied to one repository, one base revision, explicit acceptance criteria, and a delivery state.
_Avoid_: Job, ticket, prompt

**Acceptance Criterion**:
A uniquely identified, independently verifiable condition that a Task must satisfy.
_Avoid_: Requirement item, checklist entry

**Agent**:
A long-lived, Team-owned member with stable identity, capabilities, role eligibility, capacity and performance history. An Agent is not owned by a Project or Requirement and is not a model process.
_Avoid_: Project agent, bot, model instance

**Agent Profile**:
The versioned Team record describing one Agent's capabilities, eligible roles, capacity, trust and default Model Policy. It does not contain Project-specific permissions or a concrete model selection.
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

**Repository Profile**:
An immutable, integrity-checked observation of one Repository's language markers, build systems, VCS revision and native rule sources. It records facts and URI/hash references; it does not guess test commands or interpret Markdown semantics.
_Avoid_: Project Profile, generated policy, Agent memory

**Compiled Spec**:
The deterministic set of explicit structured organization, project, and Task rules admitted for one project delivery after conflict checks. It is injected into Context as one required, hash-addressed source.
_Avoid_: Prompt prose, merged Markdown

**Spec Conflict**:
An immutable record that two or more applicable structured rules cannot be safely combined. Engineering conflicts route the Work Item to `WAITING_HUMAN`; hard safety rules cannot be relaxed.
_Avoid_: Warning, Agent choice

**Spec Resolution**:
An evidence-backed human decision that resolves or terminates one Spec Conflict without rewriting its history.
_Avoid_: Chat approval, silent priority override

**Platform Workspace**:
The external durable root containing Team Workspaces and platform-level operational metadata. It never lives inside or belongs to a target code repository.
_Avoid_: Organization Workspace, Project workspace, source checkout

**Runtime Workspace Binding**:
The integrity-checked composition fact connecting one Team, one Project, one Requirement, selected Repository Profiles, fixed Runtime paths and exact target roots.
_Avoid_: Current working directory, CLI defaults

**Model Policy**:
A Team-owned rule set that defines eligible models, a default Brain Tier, risk floors and escalation signals for Agent Runs.
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

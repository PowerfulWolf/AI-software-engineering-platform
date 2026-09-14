# Spec center and learning loop

## Goal

Separate descriptive Project knowledge from enforceable engineering Specs, then turn QA and Review
failures into durable, human-approved improvements. The Team must know both *what the Project is*
and *how work must be done* without treating background documents as mandatory rules.

## Requirements

- Preserve the existing Team/Project knowledge center for business background and explanatory context.
- Add an independent Spec center with Team and Project scopes.
- Specs are immutable, versioned, content-addressed records with one explicitly active version per
  logical key.
- Each Spec declares its applicable roles, delivery stages, repositories and path globs, plus a
  human-readable verification contract.
- Team Specs apply to every Project; Project Specs apply only to their owning Project.
- Repository-native rules such as `AGENTS.md`, `.trellis/spec/**`, CI and contribution files remain a
  third source of mandatory rules.
- Requirement preparation seals the exact effective Spec versions and fails closed on conflicts or
  later drift. Team, Project and repository rules never silently override one another.
- Coder, QA and Reviewer receive applicable Specs through the existing immutable context bundle.
- Provide a deterministic Learning collector for QA `FAIL` and Review `REJECT` artifacts.
- Learning proposals retain their source evidence and require an explicit human decision.
- Approving a proposal can publish and activate a new Project Knowledge document or Project Spec
  version. A Skill recommendation is recorded as an approved design proposal but does not mutate
  executable Team skills automatically.
- Expose Spec and Learning administration in the Web Console; ordinary changes do not require a
  Console restart and affect only newly prepared Requirements.

## Acceptance Criteria

- [ ] Knowledge and Spec are visibly distinct concepts in the Console.
- [ ] Team and Project Specs cannot cross their ownership boundaries.
- [ ] Spec versions are immutable and activation is atomic.
- [ ] Preparation lists and seals the exact Team, Project and repository-native rules it consumed.
- [ ] Same logical rule key with incompatible active values stops for human resolution.
- [ ] Coder/QA/Reviewer context contains the applicable strict Spec sources.
- [ ] QA FAIL and Review REJECT artifacts can be collected into idempotent Learning proposals.
- [ ] A Learning proposal cannot publish anything without a recorded human approval.
- [ ] Approved Knowledge/Spec improvements create new immutable records and become active for future
      preparation only.
- [ ] Focused Python, API, browser, lint, type and schema tests pass; the user runs full regression.

## Decision (ADR-lite)

**Context**: Imported knowledge is intentionally read-only context. Treating it as a mandatory rule
would make arbitrary prose silently change delivery behavior. The repository already has a typed
`SpecRule` compiler and provenance checks, but the production `ProjectRuleProvider` is empty.

**Decision**: Add a typed Spec document store whose active records are compiled into `SpecRule`s.
Team Specs enter the platform-rule layer, Project Specs enter the project-rule layer through exact
sidecar provenance, and repository-native rules retain their own source lineage. Add a separate
Learning proposal store whose only publication path is a human decision.

**Consequences**: Background material stays flexible; strict rules become reviewable and auditable.
Spec edits create new versions rather than rewriting history. Existing Requirement lineage remains
stable and deliberate changes cause preparation drift rather than silent reinterpretation.

## Out of Scope

- Vector search, embeddings or automatic semantic parsing of arbitrary Markdown into atomic rules.
- Automatic conflict priority or Team-over-Project/Project-over-Team overrides.
- Automatically modifying or activating executable Agent skills.
- Complex workflow DAGs or replacing the serial Coder -> QA -> Reviewer delivery path.
- Reinterpreting already approved or completed Requirements under new knowledge or Specs.

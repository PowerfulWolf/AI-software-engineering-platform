# Evidence-backed project learning

## 1. Scope / Trigger

Applies to delivery report observations, Project Learning collection/publication and learning UI.
Knowledge is organizational memory, not a model's private transcript. Descriptive discoveries,
mandatory Specs, transient execution prerequisites and executable capabilities are distinct.

## 2. Signatures

```python
ProjectObservation(observation_id, title, fact, applicability, evidence_ids)
ImplementationReportContent.project_observations: tuple[ProjectObservation, ...]
QaReportContent.project_observations: tuple[ProjectObservation, ...]
ReviewReportContent.project_observations: tuple[ProjectObservation, ...]
ProjectLearningStore(project).collect(collected_at=None) -> tuple[LearningProposalView, ...]
ProjectLearningStore(project).decide(proposal_id, command) -> LearningProposalView
```

Existing HTTP endpoints remain GET `.../learnings`, POST `.../learnings/collect`, POST
`.../learnings/<proposal_id>/decision`. No new environment variable or database migration.
`project-observation.schema.json`, the three report schemas and `learning-proposal.schema.json`
are the wire contracts; Python validation also checks evidence references and observation-ID uniqueness.

## 3. Contracts

- Each report may carry at most eight observations, each with a bounded ID, 200-character title,
  4,000-character fact, 1,000-character applicability and 1–16 unique evidence IDs from that report.
- Absent/empty observations serialize as absent (`exclude_if`) in durable reports. Do not add an
  empty field to historical digests. Strict model transport may require an explicit empty array.
- Normal Coder, QA and Reviewer reports can propose discoveries regardless of verdict. Collection
  never interprets a proposal as proof of delivery success or accepted policy.
- `PROJECT_OBSERVATION` binds exact owning Project/Repository, Task, artifact ID/SHA, revision, role,
  observation ID, applicability and source URIs. Descriptive text and URIs are redacted before
  proposal storage; the source digest still references the original sealed artifact.
- `KNOWLEDGE_RESOLUTION` instead binds requirement/gap/resolution/previous-run. UI and JSON Schema
  must support both this variant and old finding evidence. Trigger/evidence mismatches fail closed.
- A pending or rejected proposal is not selected knowledge. Publication requires exact human
  authorization, revalidates the observation source, and retains the first immutable decision.
  KNOWLEDGE is the suggested target for discoveries; SKILL publishes only a design proposal.
- Learning knowledge publication holds the owning knowledge mutation lock from reading current
  selection through saving the union. Do not overwrite concurrent human selection changes.
- Frontend displays owner, fact, applicability, evidence, role/revision and decision state with text
  nodes; URI display does not authorize local file access. Existing report/decision records are
  never rewritten merely to improve display wording.
- New selected background enters future frozen snapshots and is retrieved/cited through existing
  role registries. Historical snapshots and QA/Review independence remain unchanged.
- Collection is currently explicit, not automatically invoked at every accepted role checkpoint.
  Upstream observation producers and Manager prerequisite-resolution integration remain open.

## 4. Validation & Error Matrix

| Input | Required result |
| --- | --- |
| Legacy report without observation field | Same canonical bytes/digest |
| Duplicate observation IDs, unknown/empty evidence IDs | Reject report |
| Repeated collection at later time | Same first proposal, no duplicates |
| Project observation submitted as knowledge resolution | Python and wire Schema reject |
| Changed/missing/corrupt source before publication | LearningError; no authorization/publication |
| Foreign Project or stale proposal digest | Reject; no memory change |
| Unapproved discovery | Invisible to future role retrieval |
| Approved scoped background | New requirements can search/read; old snapshot unchanged |
| Historical source in UI | Correct variant; never `undefined` provenance |

## 5. Good / Base / Bad Cases

Good: Requirement A discovers a repository invariant, records evidence, proposes learning; a human
confirms applicability; roles on requirement B retrieve and cite it, then independently verify B.
Base: nothing reusable was learned, so an empty observation list creates no proposal.
Bad: QA's missing local SDK becomes a universal Spec, a Coder proposal becomes QA PASS, or a
selected Skill design silently grants shell authority.

## 6. Tests Required

`tests/specs/test_project_observations.py`: all report kinds, dangling references, old-byte stability,
redaction, source revalidation, scope/stale approval rejection, idempotency and all-role A-to-B reads.
`tests/knowledge/test_effectiveness_qa.py`: approved gap-resolution schema and actual consultation.
`tests/team_view/ui.test.cjs`: finding/resolution/discovery provenance and status rendering.
Agent/schema suites must cover strict transport separately from durable legacy serialization.

## 7. Wrong vs Correct

Wrong: `QA passed -> publish all model notes as active Spec`.
Correct: `sealed scoped observation -> pending Learning -> exact human authorization -> selected
background -> future snapshot/search/read -> independent verification of the new candidate`.

## Root cause and prevention

The initial learning loop assumed every reusable insight was a failed QA/Review finding. A later
knowledge-resolution type changed Python without updating wire Schema or frontend provenance. This
was change-propagation/test-coverage failure, not a missing SDK. Every new learning source must have
one shared lifecycle fixture traversing producer, collection, approval, UI and future role retrieval.
Do not infer production integration from tests of an isolated Manager/learning component.

## Existing data and rollback

No production data is rewritten. After deploying compatible code, use the Project learning page's
collect action to gather existing observation-bearing reports; older reports without observations
cannot be retroactively claimed as learned facts. Existing approved requirements keep their context.
There is no automatic service restart. Before new records, revert this patch only; after new records,
retain readers supporting the new fields and trigger or roll forward. Never delete audit history.

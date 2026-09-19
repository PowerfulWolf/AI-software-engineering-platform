# T048 implementation design

The Knowledge Plane exposes a single `KnowledgeRetrieval` Protocol over verified,
immutable `KnowledgeDocument` and `KnowledgeSnapshot` values. A run receives a
policy-bound registry, never a filesystem path or document store. Baseline retrieval
uses bounded Markdown sections and deterministic lexical scoring, including Chinese
bigrams. An indexed implementation must pass the identical contract suite.

`KnowledgeRunBinding` pins Team, Project, Requirement, repositories, role, run, task,
source revision and context. Every query/read/refusal is an immutable evidence record;
read requires a citation from a successful search of this same run. Manifests include
the exact snapshot and evidence digests. Model content is data and cannot change scope.

Gap closure records source evidence, explicit Manager routing, trusted human approval
and new-run lineage. Resolutions do not mutate frozen selections or install Skills.
Reusable publication delegates to existing manually approved Learning. Role workflows
are versioned evidence gates, with no shell, verdict, state or approval authority.

Validation: empty/valid/foreign snapshots; digest and citation drift; missing answers;
cross-role requests; exact replay and conflict; restart and resolution lineage;
Good/Base/Bad evaluation and independent delivery QA/Review fixtures. Failed policy or
integrity checks never yield usable knowledge. Rollback: stop new runs and revert code;
immutable knowledge evidence remains readable and old requirement records stay intact.

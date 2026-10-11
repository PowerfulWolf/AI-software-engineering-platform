# Knowledge preparation local-limit interaction

## Scope / signatures

This extends the existing engineering wait UI for the typed nonterminal
KNOWLEDGE_PREPARATION_LIMIT disposition. It does not change queue authority,
retry policy, role verdicts, main invocation facts or legacy terminal recovery.

- knowledgePreparationWindowLines(evidence) -> string[] renders a finite sealed
  preparation window; absent or inconsistent numeric/policy fields return [].
- matchingKnowledgePreparationEvidence(request, step, proof) -> evidence | null
  checks the current exact Project/Requirement/Task/work/source/checkpoint/role,
  Team and available repository-root identity before offering the new decision.
- Requirement identity is evidence.delivery_requirement_id ?? evidence.requirement_id.
  The optional parent binding is supplied only by the server's verified historical
  knowledge scope/snapshot/native delivery lineage. A legacy task-scoped knowledge
  record without that explicit parent cannot offer the action; Task naming is never
  authority. An explicit wrong parent cannot fall back to the native Requirement.
- engineeringWaitCanResolve keeps current control/capability/operation, exact
  proof, no-missing, permitted-resolution and explicit engineering-duty gates.
- engineeringWaitHandlingLabel(step) chooses the visible processing entry.
- knowledgePreparationWaitExhausted(step, proof) identifies the two finite
  limits; a retained HANDLE callback rechecks this before submitting.

## Contracts

The processing entry is **让平台处理知识准备**. It submits only the existing
HANDLE_DELIVERY_WAIT exact binding. No operator ID, stop Boolean, timeout override
or evidence object is supplied by the browser. Product can request platform
handling; this request does not grant engineering authority.

RETRY_KNOWLEDGE_PREPARATION is **扩大知识准备窗口并继续**. A complete exact proof
displays its window directly next to the decision, outside troubleshooting folds:
current -> next seconds, frozen maximum, expansion 1/2 or 2/2, consumption of one
remaining frozen work allowance, and retention of original Requirement, branch,
progress and history. Independent QA/Review remain required. These labels derive
from sealed evidence, never current settings, prose or a running Operation.

The presentation validates the same finite numeric contract: roles are Coder/QA/
Reviewer, phase is intent/assessment, budget_source=frozen_work_attempt,
max=min(initial*4,86400), current=min(initial*2^(expansion-1),max),
next=min(current*2,max)>current and expansion in {1,2}. This defensive UI check
does not replace the server's full Schema, independent receipt, stopped native
execution, authority and consumption checks.

Automatic frozen-policy resolutions are recognized as recorded decisions,
distinct from human approval. The displayed decision must retain the proof's exact
knowledge evidence. Manual resolutions additionally require the current explicit
engineering permission. Clicking a retained control rechecks current exact proof,
Project/checkpoint, service capability, Team freshness and active Operations.

KNOWLEDGE_PREPARATION_UNAVAILABLE names ASE platform maintainers and the missing
or invalid execution/claim records. KNOWLEDGE_WINDOW_EXHAUSTED names engineering
owners, a frozen preparation-window limit, input/executor investigation and repair
before reevaluation. It must not be described as generic provider/model credits.
Neither that limit nor BUDGET_EXHAUSTED advertises a next execution or handling
button. The secondary state check remains for genuinely changed facts; repetition
cannot increase the window or reset historical work usage.

Current detail, complete Operation history, Task execution history and copied
reports share the resolution/missing labels and numeric window lines. Reports and
history preserve human versus organization-policy authorization. All content uses
textContent; technical IDs remain in labeled troubleshooting details.

## Validation matrix

| Input | Display / action |
| --- | --- |
| Exact proof, finite window, explicit engineering permission | Visible plan and exact new resolution button |
| Same proof with no engineering permission | Plan readable, no manual decision |
| Frozen policy automatic resolution | Saved-decision explanation and source, no repeat action |
| Wrong scope/source/role, absent evidence or invalid numeric window | No manual decision |
| Project/checkpoint/proof/capability/freshness changes after rendering | Retained callback cannot submit |
| Work or window budget exhausted | Chinese owner/action; no future-execution advertisement |
| Pending current Operation | Wait for existing result; no duplicate decision |
| Complete historical proof/resolution | Exact past window and action, never current readiness |
| Unknown future missing/resolution | Existing Chinese fail-closed fallback |

## Tests / 存量数据处置 / rollback

Incremental `tests/team_view/engineering-wait.test.cjs` covers all three roles,
first and final expansion, exact submissions, duty and numeric/scope gates,
retained callbacks, automatic result/history/report, both new missing codes,
work-budget exhaustion and known stopped execution. Related product, delivery,
Operation and capability DOM regressions retain existing behavior.

无需改库或重写旧 Operation。更新前端后重新读取原需求的精确当前记录即可显示新决定；旧终态
恢复继续使用原入口，不把英文旧错误文本当作新的非终态 proof。历史记录没有窗口字段时只显示
原有事实，不推算时限或补造审批。回滚需保留新 typed 事实的读兼容；窗口动作与对应文案一起
撤回，原审计记录和代码进度保留。

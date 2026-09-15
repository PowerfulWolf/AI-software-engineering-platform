# Design

## Data flow

`Requirement checkpoint / operation / stage receipt -> production read model -> Team queue projection -> browser cards`

`QA report evidence -> verification disposition -> retry verification | human gate | Coder remediation`

`blocked Requirement close/delete intent -> checkpoint-fenced application service -> retired Requirement projection`

## Contracts to preserve

- Do not convert verifier-environment failure into evidence of a code defect.
- Project the durable Requirement stage to exactly one upstream owner: `PREPARING` to Manager,
  `PRODUCT_DISCOVERY` to Product, `DESIGNING` to Designer, and `PLANNING` to Planner. Waiting
  stages remain assigned but are not presented as executing, and completed upstream stages move to
  that Agent's history. Never mark all four roles as running at once.
- Close and delete are distinct: close stops future delivery while retaining visibility/history; delete retires the Requirement from the current Project view while retaining immutable records.
- Browser flow copy is not authority; it renders only durable status.

## Validation matrix

| Case | Expected result |
|---|---|
| Acceptance criteria pass; unrelated configured command is `ERROR` | no Coder remediation |
| Product/Design/Plan/Manager stage is active | owning Agent queue contains one task |
| Blocked Requirement close/delete with current checkpoint | accepted and removed from active delivery control |
| Stale checkpoint close/delete | rejected with no effects |
| Continue operation becomes terminal | no persistent “Manager is redelivering” message |

## Rollback

Revert the application, projection, and UI changes together; no destructive migration is planned.

# Explicit per-Agent fallback selection

## Scope

Correct the Settings UI so the global `model_routes` collection remains only a catalog. Every
Agent policy contains one primary route plus an explicitly selected ordered fallback subset.

## Data flow

```text
enabled model_routes catalog
  -> Agent primary selector
  -> optional fallback selector
  -> add/remove/up/down operations
  -> agent_model_routes[role].routes
  -> existing ProductionConfig validation
  -> existing role-scoped runtime fallback
```

## Decisions

- Keep the existing Python and JSON Schema contracts: they already accept an ordered non-empty
  subset for each role.
- When Settings materializes a legacy empty role policy, select only the first enabled catalog route
  as primary. Do not infer fallbacks.
- Changing a primary removes the previous primary instead of silently converting it into a fallback.
- Disabling/removing a catalog route removes its reference from role policies. If no selected route
  remains, the first enabled route becomes the required primary.
- Fallback ordering is editable only below the primary; a fallback cannot be moved into position 0.

## Validation matrix

| Case | Result |
|---|---|
| New catalog route is enabled | Available to selectors; no Agent policy changes |
| Agent adds fallback | Append after existing fallbacks |
| Agent moves fallback | Swap inside fallback range only |
| Agent removes fallback | Route remains in catalog but leaves that Agent policy |
| Selected catalog route becomes unavailable | Remove stale reference; preserve remaining order |
| Legacy empty policies | Seven explicit primary-only policies |

## Tests

- Python config test proves an explicit one-route policy stays a one-route subset.
- JavaScript UI test proves enabling routes does not infer fallbacks, then covers explicit add,
  priority change and serialized order.

## Rollback

Revert the UI normalization/rendering changes. No database or Schema migration is involved.

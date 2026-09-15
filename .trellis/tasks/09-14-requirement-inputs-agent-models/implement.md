# Implementation update

- Correct `normalizeAgentModelRoutes` to preserve only valid explicitly selected routes.
- Preserve configured fallbacks when the primary changes without adding the old primary implicitly.
- Add typed UI operations for fallback add, remove, move up and move down.
- Render an explicit empty state explaining that catalog routes are not automatic fallbacks.
- Update focused Python/JavaScript tests and production documentation.

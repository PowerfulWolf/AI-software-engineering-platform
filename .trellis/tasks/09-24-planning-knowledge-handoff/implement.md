# Implementation / validation plan

- Read current knowledge/joint/Console/read-side contracts and preserve the existing CLI UI
  patch in the working tree.
- Add regressions for paused-stage presentation, exact multi-repository context, blocking
  design correction and explicit gap recheck with stale/approved/post-dispatch rejection.
- Implement typed services, endpoint intent, projection and UI; regenerate affected schemas.
- Run affected Node tests, selected pytest files, Ruff and targeted Mypy/schema parity.
- Record exact results and existing-data recovery instructions. No direct production-data
  writes or real model calls during verification.

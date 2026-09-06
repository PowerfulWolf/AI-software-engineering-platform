# Direct bootstrap repair

Changed CompanyId suffix minimum from three to two, synchronizing production config,
company manifest and requirement-project checkpoint schemas. No default-root feature,
manifest migration, permissions change, merge or push is included.

Validation on macOS:

- Regression red: 2 failed, 9 passed before implementation.
- Targeted company/config/contracts: 84 passed.
- Full pytest with dedicated existing MySQL test database: 724 passed in 109.82s.
- Ruff check, Ruff format check (441 files), strict Mypy (248 files): passed.
- Source distribution and wheel build; git diff --check: passed.

Tests use local fixtures, not real model calls. No Linux host verification claimed.
This is a user-authorized assistant repair, not a platform Coder/QA/Reviewer verdict.
Use the retained 80303b8 executor to roll back; existing company_default facts remain intact.

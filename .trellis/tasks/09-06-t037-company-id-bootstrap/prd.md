# T037 — Bootstrap repair: allow company_ai

User explicitly requested company_ai and authorized direct platform bug repair before resuming
self-delivery. The current CompanyId suffix minimum of three rejects the two-letter AI identifier.

Scope: accept safe suffixes of 2–64 characters, retaining prefix, lowercase/alphanumeric first
character and remaining lowercase/digit/underscore/hyphen constraints. Preserve all existing valid
IDs and manifest/directory integrity. No rename/migration, default change, permissions change, or
implementation of the separate default-platform-root request.

Ownership: direct assistant bootstrap repair, NOT an autonomous platform delivery verdict.

Allowed paths: company_workspace.py CompanyId definition, three company_id wire schemas,
targeted tests, company-workspace spec and this task record. Main checkout stays untouched.

Acceptance: company_ai passes config, manifest creation/reopen and Schema validation; unsafe IDs
still reject; company_default records remain byte-identical and separate. Targeted/full tests,
Ruff, strict Mypy and build pass. Rollback: use the retained 80303b8 executor; no data rewrite.

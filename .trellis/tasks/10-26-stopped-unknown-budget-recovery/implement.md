# Ownership and validation

Root: task/spec/docs, schema parity and deletion closure, integration/release, production recovery.
unknown_settlement: new domain/service, public HANDLE integration, SQL union/CAS, focused tests.
budget_recovery_path: specialized recovery source, source/plan models, current/entry, recovery tests.
unknown_public_test: real public HANDLE and exact successor approval regression, tests only.
Independent read-only review follows implementation. Contributors do not edit others' owned files.

Tests use production checkout .venv Python3.12 with PYTHONPATH=src. MySQL uses only independently
identified isolated test DB outside sandbox; tests run serially. Production state is read-only
until reviewed deployment; all later recovery uses public operations and exact existing delegation.
Rollback point: ec67fb4545499cb08402579342cdbfbb03942a54.

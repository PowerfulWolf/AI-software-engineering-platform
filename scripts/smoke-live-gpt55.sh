#!/usr/bin/env bash
set -euo pipefail

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/ase-uv-cache}"

if [[ "${ASE_RUN_LIVE_TESTS:-}" != "1" ]]; then
  echo "Refusing to consume live model quota. Set ASE_RUN_LIVE_TESTS=1 explicitly." >&2
  exit 2
fi

if [[ -z "${ASE_CONFIG:-}" || -z "${ASE_MYSQL_DSN:-}" ]]; then
  echo "ASE_CONFIG and ASE_MYSQL_DSN must be set before the live smoke run." >&2
  exit 2
fi

codex login status

smoke_root="$(mktemp -d "${TMPDIR:-/tmp}/ase-live-gpt55.XXXXXX")"
project_root="${smoke_root}/target-project"
mkdir -p "${project_root}/src" "${project_root}/tests"

printf '%s\n' \
  '[project]' \
  'name = "ase-live-smoke-target"' \
  'version = "0.1.0"' \
  'requires-python = ">=3.12"' \
  '' \
  > "${project_root}/pyproject.toml"
printf '%s\n' \
  'def greet(name: str) -> str:' \
  '    return f"Hello, {name}!"' \
  > "${project_root}/src/greetings.py"
printf '%s\n' \
  'import unittest' \
  '' \
  'from src.greetings import greet' \
  '' \
  '' \
  'class GreetingTests(unittest.TestCase):' \
  '    def test_greet(self) -> None:' \
  '        self.assertEqual(greet("Ada"), "Hello, Ada!")' \
  > "${project_root}/tests/test_greetings.py"

git -C "${project_root}" init -q
git -C "${project_root}" config user.name "ASE Live Smoke"
git -C "${project_root}" config user.email "ase-live-smoke@example.invalid"
git -C "${project_root}" add pyproject.toml src/greetings.py tests/test_greetings.py
git -C "${project_root}" commit -q -m "Initial live smoke fixture"

result_file="${smoke_root}/start.json"
uv run ase project start "${project_root}" \
  --title "GPT-5.5 production host smoke" \
  --requirement \
  "Add farewell(name: str) to src/greetings.py. It must return exactly 'Goodbye, <name>!'. Add a unittest case in tests/test_greetings.py. Do not change greet. Acceptance is python -m unittest discover -s tests -q passing." \
  > "${result_file}"

stage="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["checkpoint"]["stage"])' "${result_file}")"
if [[ "${stage}" != "WAITING_PRODUCT_APPROVAL" ]]; then
  echo "Product Agent did not reach the approval gate; inspect ${result_file}." >&2
  echo "Smoke workspace preserved at ${smoke_root}." >&2
  exit 1
fi

delivery_id="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["checkpoint"]["delivery_id"])' "${result_file}")"
checkpoint="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["checkpoint"]["checkpoint_sha256"])' "${result_file}")"
approval_file="${smoke_root}/approval.json"
uv run ase project approve "${delivery_id}" --checkpoint "${checkpoint}" > "${approval_file}"

final_stage="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["checkpoint"]["stage"])' "${approval_file}")"
candidate="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["checkpoint"].get("candidate_revision") or "")' "${approval_file}")"

echo "Live smoke stage: ${final_stage}"
echo "Delivery: ${delivery_id}"
echo "Candidate: ${candidate:-none}"
echo "Evidence and fixture preserved at: ${smoke_root}"

if [[ "${final_stage}" != "DONE" || -z "${candidate}" ]]; then
  exit 1
fi

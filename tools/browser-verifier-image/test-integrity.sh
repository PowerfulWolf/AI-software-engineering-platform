#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 COMMITTED_MANIFEST playwright-1.64.0.tgz playwright-core-1.64.0.tgz" >&2
  exit 2
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
manifest=$1
python3 "$script_dir/manifest.py" verify "$manifest" >/dev/null
fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT

mkdir "$fixture/bad"
cp -- "$2" "$fixture/bad/playwright-1.64.0.tgz"
cp -- "$3" "$fixture/bad/playwright-core-1.64.0.tgz"
printf x >> "$fixture/bad/playwright-1.64.0.tgz"
if "$script_dir/build.sh" "$fixture/bad/playwright-1.64.0.tgz" \
  "$fixture/bad/playwright-core-1.64.0.tgz" >"$fixture/bad-package.log" 2>&1; then
  echo 'tampered package was accepted' >&2
  exit 1
fi
if ! grep -q 'npm release integrity mismatch' "$fixture/bad-package.log"; then
  cat "$fixture/bad-package.log" >&2
  exit 1
fi
echo 'tampered_package=DENIED'
python3 "$script_dir/test_manifest_gate.py" "$manifest"

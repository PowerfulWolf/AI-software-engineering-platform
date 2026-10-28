#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/committed-image-manifest.json" >&2
  exit 2
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT

docker ps -a --filter 'name=ase-browser-verifier-probe-' \
  --format '{{.ID}} {{.Names}}' > "$fixture/containers-before"
docker image ls --filter 'reference=ase-browser-verifier:probe-*' \
  --format '{{.ID}} {{.Repository}}:{{.Tag}}' > "$fixture/images-before"

if (umask 077; "$script_dir/verify.sh" "$1") > "$fixture/verify.log" 2>&1; then
  result=0
else
  result=$?
fi

docker ps -a --filter 'name=ase-browser-verifier-probe-' \
  --format '{{.ID}} {{.Names}}' > "$fixture/containers-after"
docker image ls --filter 'reference=ase-browser-verifier:probe-*' \
  --format '{{.ID}} {{.Repository}}:{{.Tag}}' > "$fixture/images-after"

if ! cmp -s "$fixture/containers-before" "$fixture/containers-after" || \
   ! cmp -s "$fixture/images-before" "$fixture/images-after"; then
  echo 'synthetic probe container or image was not cleaned up' >&2
  exit 1
fi
if [[ "$result" -ne 0 ]]; then
  cat "$fixture/verify.log" >&2
  echo "synthetic probe failed under umask 077 (exit $result)" >&2
  exit 1
fi
for expected in \
  '^render_click_png=PASS bytes=[1-9][0-9]*$' \
  '^loopback_listen=DENIED code=EPERM outbound_ipv4=DENIED outbound_ipv6=DENIED$' \
  '^probe_file_write=DENIED rootfs_write=DENIED scratch_write=PASS$'; do
  if ! grep -Eq "$expected" "$fixture/verify.log"; then
    cat "$fixture/verify.log" >&2
    echo "synthetic probe omitted expected result: $expected" >&2
    exit 1
  fi
done
echo 'umask_077_synthetic_probe=PASS resources_cleaned=PASS'

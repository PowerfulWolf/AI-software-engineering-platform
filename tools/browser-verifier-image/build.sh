#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 /path/to/playwright-1.64.0.tgz /path/to/playwright-core-1.64.0.tgz" >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 - "$1" "$2" <<'PY'
import base64
import hashlib
import pathlib
import sys

expected = (
    ("playwright-1.64.0.tgz", "kVzTnYFYEyQ9RGzBjNCd2+yEqWmVbxl3AHPynv3qQ6JTjv4a+kwRcnqQwIpuP3NnrnIrE/Q6wWAIAvMfIE2/Yg=="),
    ("playwright-core-1.64.0.tgz", "T9r+MZkTECl2+oUcZ26YgZzTrYidTsIhYYkJix+6iDOymOb1FB2RLLSOxRGnZGv5DStt+aduIVbt+E8WygXYpg=="),
)
for supplied, (name, integrity) in zip(sys.argv[1:], expected):
    path = pathlib.Path(supplied)
    if not path.is_file() or path.name != name:
        raise SystemExit(f"expected regular {name}: {path}")
    actual = base64.b64encode(hashlib.sha512(path.read_bytes()).digest()).decode("ascii")
    if actual != integrity:
        raise SystemExit(f"npm release integrity mismatch: {name}")
    print(f"verified npm release integrity: {name}")
PY

base_ref='mcr.microsoft.com/playwright@sha256:68456172e8d99f42cf391e835f5d566b3ab0a2c6a745decd9590c4d73c54d2fb'
if ! base_identity=$(docker image inspect "$base_ref" --format '{{.Id}} {{.Architecture}}' 2>/dev/null); then
  echo 'pinned arm64 base image is not cached locally; refusing offline build' >&2
  exit 1
fi
if [[ "$base_identity" != 'sha256:68456172e8d99f42cf391e835f5d566b3ab0a2c6a745decd9590c4d73c54d2fb arm64' ]]; then
  echo "cached base image identity or architecture changed: $base_identity" >&2
  exit 1
fi
base_image=${base_identity%% *}
dockerfile_sha256=$(shasum -a 256 "$script_dir/Dockerfile" | awk '{print $1}')
seccomp_sha256=$(shasum -a 256 "$script_dir/seccomp-docker29-no-inet.json" | awk '{print $1}')
if [[ "$seccomp_sha256" != 65256f6a59c1f7bf76bd6eb0da3f26572e1101bbbae69ec4751668a810816949 ]]; then
  echo 'seccomp profile digest mismatch' >&2
  exit 1
fi
build_context=$(mktemp -d)
trap 'rm -rf -- "$build_context"' EXIT
cp -- "$script_dir/Dockerfile" "$build_context/Dockerfile"
cp -- "$1" "$build_context/playwright-1.64.0.tgz"
cp -- "$2" "$build_context/playwright-core-1.64.0.tgz"
docker build --network none --pull=false --platform linux/arm64 \
  --build-arg "BASE_IMAGE=$base_image" \
  --build-arg "BASE_REF=$base_ref" \
  --build-arg "PLAYWRIGHT_SHA256=55cf2db31a1d9037b050ac272bec7a824c3c9ed3ef75a6e26d6e9e89d104f155" \
  --build-arg "PLAYWRIGHT_CORE_SHA256=90c8b6b19da0a1b1e9a004cd6ff3e49e82668a0856e01efcc0e2d9c2b4466bb6" \
  --build-arg "DOCKERFILE_SHA256=$dockerfile_sha256" \
  --build-arg "SECCOMP_SHA256=$seccomp_sha256" \
  -t ase-browser-verifier:offline-1.64.0 "$build_context"
docker image inspect ase-browser-verifier:offline-1.64.0 \
  --format 'local image ID={{.Id}} architecture={{.Architecture}}'
manifest_path=$(python3 "$script_dir/manifest.py" create)
echo "committed-manifest candidate=$manifest_path"
echo 'Commit the generated manifest before running verify.sh.'

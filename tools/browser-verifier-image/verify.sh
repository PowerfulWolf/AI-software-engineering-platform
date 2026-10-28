#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/committed-image-manifest.json" >&2
  exit 2
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
profile="$script_dir/seccomp-docker29-no-inet.json"
actual_profile=$(shasum -a 256 "$profile" | awk '{print $1}')
if [[ "$actual_profile" != 65256f6a59c1f7bf76bd6eb0da3f26572e1101bbbae69ec4751668a810816949 ]]; then
  echo 'seccomp profile digest mismatch' >&2
  exit 1
fi

base_image=$(python3 "$script_dir/manifest.py" verify "$1")
owner_token=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
probe_tag="ase-browser-verifier:probe-$owner_token"
probe_name="ase-browser-verifier-probe-$owner_token"
build_context=$(mktemp -d)
cleanup() {
  observed_owner=$(docker inspect "$probe_name" --format '{{index .Config.Labels "org.ase.synthetic-probe.owner"}}' 2>/dev/null || true)
  if [[ "$observed_owner" == "$owner_token" ]]; then
    docker rm -f "$probe_name" >/dev/null 2>&1 || true
  fi
  docker image rm "$probe_tag" >/dev/null 2>&1 || true
  rm -rf -- "$build_context"
}
trap cleanup EXIT
cp -- "$script_dir/Dockerfile.probe" "$build_context/Dockerfile"
cp -- "$script_dir/probe.cjs" "$build_context/probe.cjs"
chmod 0444 "$build_context/probe.cjs"
docker build --network none --pull=false --build-arg "BASE_IMAGE=$base_image" \
  -t "$probe_tag" "$build_context"
docker run --name "$probe_name" --label "org.ase.synthetic-probe.owner=$owner_token" --rm --pull never --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --security-opt "seccomp=$profile" --pids-limit 256 --memory 1g \
  --memory-swap 1g --cpus 1 --ulimit nofile=1024:1024 \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m \
  --tmpfs /home/pwuser:rw,nosuid,nodev,size=32m --shm-size 64m \
  "$probe_tag" /usr/bin/timeout --kill-after=5 30 node /work/probe.cjs

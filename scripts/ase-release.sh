#!/bin/sh
# Run ASE from a pinned release instead of the checkout ASE is developing.
#
# The development checkout is also a target Repository: ASE's own Coder,
# QA and Reviewer change it. Running the service from that same editable
# checkout means every platform fix silently changes the engine under a
# frozen Task. A release is a separate, read-only clone of one tag with its
# own .venv; switching releases goes through the normal controlled restart.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
DEV_REPO=${ASE_DEV_REPO:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)}
DEFAULT_DATA_BASE=${XDG_DATA_HOME:-"${HOME:?HOME is required}/.local/share"}
RUNTIME_HOME=${ASE_RUNTIME_HOME:-"$DEFAULT_DATA_BASE/ai-software-engineer/runtime"}
RELEASES="$RUNTIME_HOME/releases"
CURRENT_LINK="$RUNTIME_HOME/current"
PREVIOUS_FILE="$RUNTIME_HOME/previous"

usage() {
  cat <<'EOF'
Usage: ase-release.sh COMMAND [TAG]

  tag TAG        Create annotated tag TAG at the clean HEAD of the dev checkout.
  install TAG    Clone TAG into its own release directory and build its .venv.
  activate TAG   Switch the running service to TAG via the controlled restart.
  rollback       Re-activate the release that was current before the last switch.
  status         Show the active release and installed releases.

Environment: ASE_RUNTIME_HOME (default ~/.local/share/ai-software-engineer/runtime),
ASE_DEV_REPO (default: the checkout containing this script).
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

require_tag_name() {
  case "${1:-}" in
    '') usage >&2; exit 2 ;;
    v[0-9]*) ;;
    *) fail "release tags must look like v0.1.4, got: $1" ;;
  esac
  case "$1" in
    *[!A-Za-z0-9._-]*) fail "release tag contains unsupported characters: $1" ;;
  esac
}

release_dir() {
  printf '%s/%s\n' "$RELEASES" "$1"
}

current_tag() {
  [ -L "$CURRENT_LINK" ] || return 1
  basename -- "$(readlink "$CURRENT_LINK")"
}

cmd_tag() {
  tag=$1
  require_tag_name "$tag"
  cd "$DEV_REPO"
  [ -z "$(git status --porcelain --untracked-files=no)" ] \
    || fail "dev checkout has uncommitted tracked changes; commit or stash them first"
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    fail "tag $tag already exists"
  fi
  git tag -a "$tag" -m "ASE runtime release $tag"
  echo "tagged $tag at $(git rev-parse --short HEAD)"
}

cmd_install() {
  tag=$1
  require_tag_name "$tag"
  command -v uv >/dev/null 2>&1 || fail "uv is required"
  git -C "$DEV_REPO" rev-parse -q --verify "refs/tags/$tag^{commit}" >/dev/null \
    || fail "tag $tag does not exist in $DEV_REPO"
  dest=$(release_dir "$tag")
  if [ -e "$dest" ]; then
    fail "release $tag is already installed at $dest"
  fi
  mkdir -p "$RELEASES"
  staging="$RELEASES/.installing-$tag.$$"
  trap 'chmod -R u+w "$staging" 2>/dev/null || true; rm -rf "$staging"' EXIT INT TERM
  # A full independent clone: release directories never share Git state with
  # the worktrees ASE creates in the development repository.
  git clone --quiet --no-local --branch "$tag" "$DEV_REPO" "$staging"
  (
    cd "$staging"
    git -c advice.detachedHead=false checkout --quiet "$tag"
    uv sync --frozen --no-dev
    # Compile once while writable; the read-only source then loads from cache.
    .venv/bin/python -m compileall -q src >/dev/null
  )
  # The engine source of a release is never edited in place.
  chmod -R a-w "$staging/src"
  mv "$staging" "$dest"
  trap - EXIT INT TERM
  echo "installed $tag at $dest"
}

cmd_activate() {
  tag=$1
  require_tag_name "$tag"
  dest=$(release_dir "$tag")
  [ -x "$dest/.venv/bin/ase-console" ] || fail "release $tag is not installed; run: $0 install $tag"
  previous=$(current_tag 2>/dev/null || true)
  # The controlled restart drains the running service (from any checkout or
  # release) and starts the replacement from this release's own executable.
  "$dest/scripts/ase-console-service.sh" restart
  if [ -n "$previous" ] && [ "$previous" != "$tag" ]; then
    printf '%s\n' "$previous" > "$PREVIOUS_FILE"
  fi
  ln -sfn "$dest" "$CURRENT_LINK"
  echo "active release: $tag"
}

cmd_rollback() {
  [ -f "$PREVIOUS_FILE" ] || fail "no previous release is recorded"
  cmd_activate "$(sed -n '1p' "$PREVIOUS_FILE")"
}

cmd_status() {
  active=$(current_tag 2>/dev/null || echo "(none: service runs from a development checkout)")
  echo "active release: $active"
  if [ -f "$PREVIOUS_FILE" ]; then
    echo "previous release: $(sed -n '1p' "$PREVIOUS_FILE")"
  fi
  echo "installed releases in $RELEASES:"
  if [ -d "$RELEASES" ]; then
    for path in "$RELEASES"/v*; do
      [ -d "$path" ] || continue
      echo "  $(basename -- "$path") ($(git -C "$path" rev-parse --short HEAD))"
    done
  fi
  if [ -L "$CURRENT_LINK" ]; then
    "$CURRENT_LINK/scripts/ase-console-service.sh" status || true
  fi
}

command=${1:-}
case "$command" in
  tag) cmd_tag "${2:-}" ;;
  install) cmd_install "${2:-}" ;;
  activate) cmd_activate "${2:-}" ;;
  rollback) cmd_rollback ;;
  status) cmd_status ;;
  -h|--help|help) usage ;;
  *) usage >&2; exit 2 ;;
esac

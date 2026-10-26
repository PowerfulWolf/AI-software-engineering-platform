"""Read-only negatives for the committed image identity and config-label gate."""

import copy
import sys

import manifest


def rejected(manifest_path, image, expected_reason):
    try:
        manifest.verify(manifest_path, image_lookup=lambda _reference: image)
    except SystemExit as exc:
        if str(exc) != expected_reason:
            raise AssertionError(f"unexpected rejection: {exc}") from exc
    else:
        raise AssertionError("modified image inspection was accepted")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_manifest_gate.py COMMITTED_MANIFEST")
    manifest_path = sys.argv[1]
    live = manifest.docker_image(manifest.TAG)
    base = manifest.docker_image(manifest.BASE_ID)
    rejected(manifest_path, base, "offline image tag points to a different image ID")
    print("wrong_image_id=DENIED")

    changed_label = copy.deepcopy(live)
    label = manifest.LABEL_PREFIX + "dockerfile-sha256"
    changed_label["Config"]["Labels"][label] = "0" * 64
    rejected(
        manifest_path,
        changed_label,
        "Docker image build label mismatch: " + label,
    )
    print("changed_label=DENIED")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Bind a local offline browser image to committed, content-addressed build facts."""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MANIFESTS = HERE / "manifests"
TAG = "ase-browser-verifier:offline-1.64.0"
BASE_REF = (
    "mcr.microsoft.com/playwright@sha256:"
    "68456172e8d99f42cf391e835f5d566b3ab0a2c6a745decd9590c4d73c54d2fb"
)
BASE_ID = "sha256:68456172e8d99f42cf391e835f5d566b3ab0a2c6a745decd9590c4d73c54d2fb"
PLAYWRIGHT_SHA256 = "55cf2db31a1d9037b050ac272bec7a824c3c9ed3ef75a6e26d6e9e89d104f155"
CORE_SHA256 = "90c8b6b19da0a1b1e9a004cd6ff3e49e82668a0856e01efcc0e2d9c2b4466bb6"
SECCOMP_SHA256 = "65256f6a59c1f7bf76bd6eb0da3f26572e1101bbbae69ec4751668a810816949"
LABEL_PREFIX = "org.ase.browser-verifier."


def fail(message):
    raise SystemExit(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def docker_image(reference):
    result = subprocess.run(
        ["docker", "image", "inspect", reference, "--format", "{{json .}}"],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        fail("local Docker image unavailable: " + reference)
    try:
        image = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError):
        fail("Docker image inspection returned invalid JSON")
    if not isinstance(image, dict):
        fail("Docker image inspection returned invalid object")
    return image


def expected_fields():
    dockerfile_sha = sha256(HERE / "Dockerfile")
    seccomp_sha = sha256(HERE / "seccomp-docker29-no-inet.json")
    if seccomp_sha != SECCOMP_SHA256:
        fail("seccomp profile digest mismatch")
    return {
        "schema_version": "offline-browser-image-v1",
        "tag": TAG,
        "architecture": "arm64",
        "base_ref": BASE_REF,
        "base_image_id": BASE_ID,
        "playwright_sha256": PLAYWRIGHT_SHA256,
        "playwright_core_sha256": CORE_SHA256,
        "dockerfile_sha256": dockerfile_sha,
        "seccomp_sha256": seccomp_sha,
    }


def expected_labels(fields):
    return {
        LABEL_PREFIX + "schema": fields["schema_version"],
        LABEL_PREFIX + "base-ref": fields["base_ref"],
        LABEL_PREFIX + "base-id": fields["base_image_id"],
        LABEL_PREFIX + "playwright-sha256": fields["playwright_sha256"],
        LABEL_PREFIX + "playwright-core-sha256": fields["playwright_core_sha256"],
        LABEL_PREFIX + "dockerfile-sha256": fields["dockerfile_sha256"],
        LABEL_PREFIX + "seccomp-sha256": fields["seccomp_sha256"],
    }


def validate_image(image, fields):
    image_id = image.get("Id")
    if not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        fail("Docker image ID is invalid")
    if image.get("Architecture") != "arm64":
        fail("Docker image architecture differs from manifest")
    config = image.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        fail("Docker image is missing build labels")
    for key, value in expected_labels(fields).items():
        if labels.get(key) != value:
            fail("Docker image build label mismatch: " + key)
    return image_id


def record_bytes(record):
    return (json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def create():
    fields = expected_fields()
    image_id = validate_image(docker_image(TAG), fields)
    record = dict(fields, image_id=image_id)
    record["manifest_sha256"] = digest(record)
    raw = record_bytes(record)
    MANIFESTS.mkdir(mode=0o755, exist_ok=True)
    if not stat.S_ISDIR(MANIFESTS.lstat().st_mode):
        fail("manifests directory must be a real directory")
    path = MANIFESTS / ("sha256-" + image_id[7:] + ".json")
    try:
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError:
        if path.read_bytes() != raw:
            fail("existing image manifest differs; refusing overwrite")
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(str(path), 0o444)
    print(path)


def load_committed(path_arg):
    path = Path(path_arg)
    try:
        metadata = path.lstat()
    except OSError:
        fail("image manifest missing")
    if not stat.S_ISREG(metadata.st_mode):
        fail("image manifest must be a regular file")
    if not stat.S_ISDIR(MANIFESTS.lstat().st_mode):
        fail("manifests directory must be a real directory")
    path = path.resolve()
    if (
        path.parent != MANIFESTS.resolve()
        or re.fullmatch(r"sha256-[0-9a-f]{64}\.json", path.name) is None
    ):
        fail("image manifest must be in the fixed manifests directory")
    try:
        rel = path.relative_to(REPO)
    except ValueError:
        fail("image manifest escaped repository")
    result = subprocess.run(
        ["git", "-C", str(REPO), "show", "HEAD:" + rel.as_posix()],
        capture_output=True,
        check=False,
    )
    if result.returncode or result.stdout != path.read_bytes():
        fail("image manifest is not the exact committed Git blob")
    return path, result.stdout


def verify(path_arg, image_lookup=docker_image):
    path, raw = load_committed(path_arg)
    try:
        record = json.loads(raw)
    except ValueError:
        fail("image manifest is invalid JSON")
    if not isinstance(record, dict) or record_bytes(record) != raw:
        fail("image manifest is not canonical JSON")
    expected = expected_fields()
    expected_keys = set(expected) | {"image_id", "manifest_sha256"}
    if set(record) != expected_keys:
        fail("image manifest fields differ from v1 contract")
    for key, value in expected.items():
        if record[key] != value:
            fail("image manifest input mismatch: " + key)
    payload = {key: value for key, value in record.items() if key != "manifest_sha256"}
    if record["manifest_sha256"] != digest(payload):
        fail("image manifest digest mismatch")
    image_id = record["image_id"]
    if (
        not isinstance(image_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or path.name != "sha256-" + image_id[7:] + ".json"
    ):
        fail("image manifest path does not match image ID")
    image = image_lookup(TAG)
    if image.get("Id") != image_id:
        fail("offline image tag points to a different image ID")
    validate_image(image, expected)
    print(image_id)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "create":
        create()
    elif len(sys.argv) == 3 and sys.argv[1] == "verify":
        verify(sys.argv[2])
    else:
        fail("usage: manifest.py create | verify MANIFEST.json")


if __name__ == "__main__":
    main()

# Offline browser-verifier image research fixture

This local image packages `playwright` and `playwright-core` 1.64.0 on the cached
Linux/arm64 Playwright base image. It is a reproducible **synthetic test prerequisite**,
not a registered ASE QA/Reviewer capability or K1 acceptance result.

The base image is pinned to
`mcr.microsoft.com/playwright@sha256:68456172e8d99f42cf391e835f5d566b3ab0a2c6a745decd9590c4d73c54d2fb`.
`build.sh` verifies both tarballs against the official npm release SHA-512 integrity
values and requires the exact arm64 base image to be present locally before passing
inputs to Docker. The Dockerfile checks their SHA-256 again,
uses no network during build, skips browser download and installs no lifecycle scripts.
The `playwright-core` package requests Chromium revision 1248, which is present
in the pinned base image; the synthetic launch/click/PNG probe confirms runtime
compatibility on this arm64 host. The tarballs stay outside Git. Obtain exact
package bytes through an authorized package source and supply them as explicit
arguments:

```sh
tools/browser-verifier-image/build.sh \
  /path/to/playwright-1.64.0.tgz \
  /path/to/playwright-core-1.64.0.tgz
# Commit the generated manifests/sha256-<image-id>.json with this recipe.
tools/browser-verifier-image/verify.sh \
  /absolute/path/printed/by/build.sh.json
```

The image has config labels for its base reference and ID, package SHA-256 values,
Dockerfile SHA-256 and seccomp SHA-256. `build.sh` writes a content-addressed,
write-once manifest containing those facts and the resulting image ID. Commit that
manifest before verification. `verify.sh` requires its exact committed Git blob,
checks all input hashes and image labels, and rejects a locally overwritten tag
before creating any probe resource. `test-integrity.sh` exercises read-only
wrong-image-ID and changed-label inputs, plus tampered-package rejection.

`verify.sh` checks the frozen Docker 29 seccomp profile, builds an ephemeral probe
layer and runs a synthetic Node/Chromium click-and-PNG test. The container has no
network, is non-root, has a read-only root filesystem, no Linux capabilities, no
new privileges, a fixed seccomp profile blocking internet socket creation, and
bounded CPU/memory/PIDs/scratch. It checks real loopback listening and outbound
IPv4/IPv6 socket denial, probe-layer file and rootfs write denial, and writable
private scratch. Chromium's inner sandbox is explicitly disabled; the outer
Docker boundary contains the process tree.

The image and probe do not bind a K1 candidate, role claim, read/deny inventory,
trusted receipt, independent QA/Review, or live A-to-B provider path. Those remain
separate gates before any production registration. An installed image or successful
synthetic probe must never be reported as K1 QA PASS.

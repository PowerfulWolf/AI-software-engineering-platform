# Cached arm64 base manifest: mcr.microsoft.com/playwright@sha256:68456172e8d99f42cf391e835f5d566b3ab0a2c6a745decd9590c4d73c54d2fb
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG BASE_IMAGE
ARG BASE_REF
ARG PLAYWRIGHT_SHA256
ARG PLAYWRIGHT_CORE_SHA256
ARG DOCKERFILE_SHA256
ARG SECCOMP_SHA256
LABEL org.ase.browser-verifier.schema="offline-browser-image-v1" \
      org.ase.browser-verifier.base-ref="$BASE_REF" \
      org.ase.browser-verifier.base-id="$BASE_IMAGE" \
      org.ase.browser-verifier.playwright-sha256="$PLAYWRIGHT_SHA256" \
      org.ase.browser-verifier.playwright-core-sha256="$PLAYWRIGHT_CORE_SHA256" \
      org.ase.browser-verifier.dockerfile-sha256="$DOCKERFILE_SHA256" \
      org.ase.browser-verifier.seccomp-sha256="$SECCOMP_SHA256"
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY playwright-1.64.0.tgz playwright-core-1.64.0.tgz /tmp/
RUN printf '%s\n' '55cf2db31a1d9037b050ac272bec7a824c3c9ed3ef75a6e26d6e9e89d104f155  /tmp/playwright-1.64.0.tgz' '90c8b6b19da0a1b1e9a004cd6ff3e49e82668a0856e01efcc0e2d9c2b4466bb6  /tmp/playwright-core-1.64.0.tgz' | sha256sum -c - \
    && npm install --prefix /opt/ase-browser --offline --ignore-scripts --no-audit --no-fund /tmp/playwright-core-1.64.0.tgz /tmp/playwright-1.64.0.tgz \
    && rm -f /tmp/playwright-1.64.0.tgz /tmp/playwright-core-1.64.0.tgz
ENV NODE_PATH=/opt/ase-browser/node_modules
USER pwuser
WORKDIR /work
CMD ["node", "--version"]

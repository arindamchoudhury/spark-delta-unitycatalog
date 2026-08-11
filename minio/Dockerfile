# syntax=docker/dockerfile:1
#
# MinIO stopped publishing community container images after
# RELEASE.2025-09-07T16-13-09Z. The next (and so far only) release,
# RELEASE.2025-10-15T17-29-55Z, fixes GHSA-jjjj-jwhf-8rgr -- privilege
# escalation via session policy bypass in service accounts and STS -- and was
# never pushed to Docker Hub or quay.io. Upstream's guidance for that release
# is "clone the source and build the latest container".
#
# Upstream's own Dockerfile expects a ./minio binary already built on the host
# (`make docker` depends on `make build`). This builds the binary inside Docker
# instead, then layers it onto the last published image so the entrypoint,
# helper scripts and image metadata all stay upstream's.

# Deliberately not named MINIO_RELEASE: Docker exposes ARGs as env vars to RUN,
# and gen-ldflags.go reads $MINIO_RELEASE as the release-tag *prefix* (upstream
# sets it to the literal "RELEASE"). Reusing that name doubles the version string.
ARG MINIO_TAG=RELEASE.2025-10-15T17-29-55Z
# Last image MinIO published; supplies the entrypoint and base filesystem.
ARG MINIO_BASE=minio/minio:RELEASE.2025-09-07T16-13-09Z
# Matches the `toolchain` directive in go.mod at MINIO_RELEASE.
ARG GO_VERSION=1.24.8

FROM golang:${GO_VERSION}-bookworm AS build

ARG MINIO_TAG
WORKDIR /src

# Shallow clone at the tag: gen-ldflags.go reads the commit time and commit id
# from git, so the checkout has to be a real repo, not a source tarball.
RUN git clone --depth 1 --branch "${MINIO_TAG}" \
        https://github.com/minio/minio.git . \
 && git rev-parse HEAD

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download

# Same flags as upstream `make build`, minus the lint/debugging-tool targets
# that only matter in their CI. LDFLAGS stamp Version/ReleaseTag/CommitID so
# `minio --version` reports the real release rather than DEVELOPMENT.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    set -eux; \
    LDFLAGS="$(MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go)"; \
    echo "LDFLAGS: ${LDFLAGS}"; \
    CGO_ENABLED=0 go build -tags kqueue -trimpath --ldflags "${LDFLAGS}" -o /out/minio; \
    /out/minio --version


FROM ${MINIO_BASE}

ARG MINIO_TAG
LABEL org.opencontainers.image.version="${MINIO_TAG}" \
      org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.description="MinIO built from source at ${MINIO_TAG} (GHSA-jjjj-jwhf-8rgr fix); no upstream image exists for this release."

COPY --from=build --chmod=755 /out/minio /usr/bin/minio
COPY --from=build --chmod=755 /src/dockerscripts/docker-entrypoint.sh /usr/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/bin/docker-entrypoint.sh"]
VOLUME ["/data"]
CMD ["minio"]

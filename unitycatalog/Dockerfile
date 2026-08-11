# syntax=docker/dockerfile:1.7-labs
#
# Unity Catalog server built from source.
#
# Unity Catalog publishes server images only for minor releases -- the newest on
# Docker Hub is v0.5.0, while the jars pinned in spark/Dockerfile are 0.5.1.
# This builds the matching v0.5.1 server.
#
# Mirrors upstream's root Dockerfile at the same tag, with one required change.
# bin/start-uc-server launches the server with `java -cp $(cat
# server/target/classpath)`, and that file holds *absolute* jar paths baked at
# build time. Upstream relies on `ENV HOME` to steer sbt's coursier cache under
# $HOME so the copy at the end of the build stage keeps those paths valid -- but
# the JVM derives user.home from the passwd entry, which for uid 0 is /root.
# Coursier then caches to /root/.cache, $HOME/.cache is empty, and the resulting
# image starts with 257 of 259 classpath entries missing. COURSIER_CACHE is
# honoured directly and pins the cache where the copy expects it.

ARG UC_TAG=v0.5.1
ARG HOME="/home/unitycatalog"
ARG JAVA_HOME="/usr/lib/jvm/default-jvm"
ARG USER="unitycatalog"

FROM amazoncorretto:17-alpine3.20-jdk AS base

ARG UC_TAG
ARG HOME
ENV HOME=$HOME
# The reason this file exists -- see header.
ENV COURSIER_CACHE="$HOME/.cache/coursier"

WORKDIR $HOME

RUN apk add --no-cache bash git

# Clone into $HOME so the runtime stage can take bin/ and etc/ from here rather
# than from a build context, keeping the whole build self-contained.
RUN git clone --depth 1 --branch "$UC_TAG" \
        https://github.com/unitycatalog/unitycatalog.git . \
 && git rev-parse HEAD \
 && rm -rf .git

RUN ./build/sbt -info clean package


FROM alpine:3.20 AS runtime

ARG UC_TAG
ARG JAVA_HOME
ARG USER
ARG HOME

LABEL org.opencontainers.image.version="${UC_TAG}" \
      org.opencontainers.image.source="https://github.com/unitycatalog/unitycatalog" \
      org.opencontainers.image.description="Unity Catalog server built from source at ${UC_TAG}; upstream publishes server images for minor releases only."

COPY --from=base $JAVA_HOME $JAVA_HOME

ENV HOME=$HOME \
    JAVA_HOME=$JAVA_HOME \
    PATH="${JAVA_HOME}/bin:${PATH}"

COPY --from=base --parents \
    $HOME/examples/ \
    $HOME/server/ \
    $HOME/api/ \
    $HOME/clients/ \
    $HOME/target/ \
    $HOME/.cache/ \
    /

RUN <<EOF
apk add --no-cache bash
addgroup -S $USER
adduser -S -G $USER $USER
chmod -R 550 $HOME
mkdir -p $HOME/etc/
chmod -R 770 $HOME/etc/
chown -R $USER:$USER $HOME
EOF

USER $USER

COPY --from=base --chown=$USER:$USER --parents $HOME/bin/ $HOME/etc/ /

WORKDIR $HOME

CMD ["./bin/start-uc-server"]

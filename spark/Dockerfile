# syntax=docker/dockerfile:1

# ---------- Stage 1: Build Spark from branch-4.2 ----------
FROM eclipse-temurin:21 AS spark-builder

# build/mvn (Spark's wrapper) needs curl to download the exact Maven version
# from pom.xml; python3 is called by make-distribution.sh for pip packaging.
# System maven is NOT used — build/mvn downloads the correct version itself.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# ARG placed here so changing it only busts layers from git clone onward,
# not the apt-get layer above.
ARG SPARK_BRANCH_SHA=latest
RUN git clone --branch branch-4.2 --depth 1 \
        https://github.com/apache/spark.git

WORKDIR /build/spark
RUN --mount=type=cache,target=/root/.m2 \
    --mount=type=cache,target=/build/spark/build \
    MAVEN_OPTS="-Xss128m -Xmx4g -XX:ReservedCodeCacheSize=128m" \
    ./dev/make-distribution.sh \
        --name hadoop3-connect \
        --tgz \
        -Phadoop-3 \
    && mv spark-*-bin-hadoop3-connect.tgz /spark.tgz

# ---------- Stage 2: Runtime image ----------
FROM eclipse-temurin:21-resolute

ARG spark_uid=185

# ---------- Version pins (read by download_deps.py) ----------
ENV HADOOP_VERSION=3.4.3 \
    SPARK_VERSION=4.2.0-SNAPSHOT \
    SCALA_VERSION=2.13 \
    HADOOP_AWS_VERSION=3.4.3 \
    AWS_SDK_BUNDLE_VERSION=2.35.4 \
    AWS_ANALYTICS_ACCELERATOR_VERSION=1.3.1 \
    WILDFLY_OPENSSL_VERSION=2.2.5.Final \
    UNITYCATALOG_VERSION=0.4.1 \
    DELTA_VERSION=4.2.0

# ---------- Spark user ----------
RUN groupadd --system --gid=${spark_uid} spark && \
    useradd --system --uid=${spark_uid} --gid=spark -d /nonexistent spark

# ---------- Preflight: verify downloaded artifacts ----------
RUN --mount=type=bind,source=.,target=/src \
    set -e; \
    missing=""; \
    for f in \
        "spark/tar/hadoop-${HADOOP_VERSION}.tar.gz" \
        "spark/jar/hadoop-aws-${HADOOP_AWS_VERSION}.jar" \
        "spark/jar/bundle-${AWS_SDK_BUNDLE_VERSION}.jar" \
        "spark/jar/analyticsaccelerator-s3-${AWS_ANALYTICS_ACCELERATOR_VERSION}.jar" \
        "spark/jar/wildfly-openssl-${WILDFLY_OPENSSL_VERSION}.jar" \
        "spark/jar/unitycatalog-client-${UNITYCATALOG_VERSION}.jar" \
        "spark/jar/unitycatalog-spark_${SCALA_VERSION}-${UNITYCATALOG_VERSION}.jar" \
        "spark/jar/delta-spark_${SCALA_VERSION}-${DELTA_VERSION}.jar" \
        "spark/jar/delta-storage-${DELTA_VERSION}.jar"; \
    do \
        [ -f "/src/$f" ] || missing="${missing}  $f\n"; \
    done; \
    if [ -n "$missing" ]; then \
        printf "\nERROR: Missing required files:\n%b\nRun from the project root:\n  python download_deps.py\n\n" "$missing" >&2; \
        exit 1; \
    fi

# ---------- System deps + Python 3.14 (native in Ubuntu 26.04) ----------
RUN set -ex; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        gnupg2 wget bash tini libc6 libpam-modules krb5-user libnss3 \
        procps net-tools gosu libnss-wrapper \
        ca-certificates curl \
        libsnappy1v5 libzstd1 liblz4-1 \
        python3.14 python3.14-venv python3.14-dev; \
    mkdir -p /opt/spark/python /opt/spark/examples /opt/spark/work-dir; \
    chmod g+w /opt/spark/work-dir; \
    touch /opt/spark/RELEASE; \
    chown -R spark:spark /opt/spark; \
    echo "auth required pam_wheel.so use_uid" >> /etc/pam.d/su; \
    rm -rf /var/lib/apt/lists/*

# ---------- Install Spark from branch-4.2 build ----------
COPY --from=spark-builder /spark.tgz /tmp/spark.tgz
RUN set -ex; \
    export SPARK_TMP="$(mktemp -d)"; \
    tar -xf /tmp/spark.tgz -C "$SPARK_TMP" --strip-components=1; \
    cd "$SPARK_TMP"; \
    chown -R spark:spark .; \
    mv jars /opt/spark/; \
    mv RELEASE /opt/spark/; \
    mv bin /opt/spark/; \
    mv sbin /opt/spark/; \
    mv examples /opt/spark/; \
    ln -s "$(basename /opt/spark/examples/jars/spark-examples_*.jar)" /opt/spark/examples/jars/spark-examples.jar; \
    mv data /opt/spark/; \
    mv python/pyspark /opt/spark/python/pyspark/; \
    mv python/lib /opt/spark/python/lib/; \
    mv kubernetes/tests /opt/spark/ 2>/dev/null || true; \
    mv kubernetes/dockerfiles/spark/decom.sh /opt/ 2>/dev/null || true; \
    mv R /opt/spark/ 2>/dev/null || true; \
    chmod a+x /opt/decom.sh 2>/dev/null || true; \
    rm -f /tmp/spark.tgz; \
    rm -rf "$SPARK_TMP"

COPY spark/entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh

ENV SPARK_HOME=/opt/spark

# ---------- Hadoop ----------
RUN --mount=type=bind,source=spark/tar/hadoop-3.4.3.tar.gz,target=/tmp/hadoop.tar.gz \
    tar -xzf /tmp/hadoop.tar.gz -C /opt \
    && mv "/opt/hadoop-${HADOOP_VERSION}" /opt/hadoop

ENV HADOOP_HOME=/opt/hadoop \
    HADOOP_COMMON_LIB_NATIVE_DIR=/opt/hadoop/lib/native \
    LD_LIBRARY_PATH=/opt/hadoop/lib/native \
    SPARK_DIST_CLASSPATH=/opt/hadoop/share/hadoop/common/*:/opt/hadoop/share/hadoop/common/lib/*:/opt/hadoop/share/hadoop/hdfs/*:/opt/hadoop/share/hadoop/hdfs/lib/*:/opt/hadoop/share/hadoop/mapreduce/*:/opt/hadoop/share/hadoop/mapreduce/lib/*:/opt/hadoop/share/hadoop/yarn/*:/opt/hadoop/share/hadoop/yarn/lib/*

# ---------- S3A, Delta, Unity Catalog jars ----------
RUN --mount=type=bind,source=spark/jar,target=/tmp/jars \
    cp /tmp/jars/*.jar /opt/spark/jars/

# ---------- Python 3.14 venv ----------
RUN python3.14 -m venv /opt/envs/spark && chown -R spark:spark /opt/envs/spark

ENV PATH="/opt/envs/spark/bin:$PATH" \
    JUPYTER_PATH="/opt/envs/spark/share/jupyter" \
    IPYTHONDIR="/opt/envs/spark/share/ipython" \
    PYSPARK_PYTHON=/opt/envs/spark/bin/python \
    PYSPARK_DRIVER_PYTHON=/opt/envs/spark/bin/python

WORKDIR /opt/spark/work-dir

USER spark

RUN pip install --no-cache-dir \
    ipykernel \
    "pandas<3" scikit-learn pyarrow grpcio grpcio-status zstandard \
    dagster==1.13.2 dagster-webserver==1.13.2 dagstermill==0.29.2 papermill \
    dagster-postgres==0.29.2 psycopg2-binary awscli uv \
    unitycatalog-ai==0.4.0 \
    unitycatalog-openai==0.4.0 \
    unitycatalog-anthropic==0.2.0 \
    unitycatalog-langchain==0.4.0

# Use the tarball's PySpark instead of a pip-installed copy so the daemon
# and workers load from identical files. A .pth file wires both pyspark and
# py4j into the venv without duplicating them.
RUN echo "/opt/spark/python" > /opt/envs/spark/lib/python3.14/site-packages/spark.pth \
 && find /opt/spark/python/lib -name "py4j*.zip" >> /opt/envs/spark/lib/python3.14/site-packages/spark.pth

RUN python3 -m ipykernel install --sys-prefix --name spark --display-name "spark"

ENTRYPOINT ["/opt/entrypoint.sh"]

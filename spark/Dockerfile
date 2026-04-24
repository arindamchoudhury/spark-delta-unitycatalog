FROM apache/spark:4.1.1-scala2.13-java21-python3-ubuntu

USER root

ENV HADOOP_VERSION=3.4.3
ENV HADOOP_AWS_VERSION=3.4.3
ENV AWS_SDK_BUNDLE_VERSION=2.35.4
ENV AWS_ANALYTICS_ACCELERATOR_VERSION=1.3.1
ENV WILDFLY_OPENSSL_VERSION=2.2.5.Final
ENV UNITYCATALOG_VERSION=0.4.0
ENV DELTA_VERSION=4.1.0

# Install runtime dependencies for Hadoop native libs.
RUN apt-get update && apt-get install -y --no-install-recommends \
	ca-certificates \
	curl \
	libsnappy1v5 \
	libzstd1 \
	liblz4-1 \
	&& rm -rf /var/lib/apt/lists/*

COPY spark/tar/hadoop-3.4.3.tar.gz /tmp/hadoop-3.4.3.tar.gz

# Add Hadoop native libraries so Spark can use JNI acceleration where available.
RUN tar -xzf /tmp/hadoop-3.4.3.tar.gz -C /opt \
	&& mv "/opt/hadoop-${HADOOP_VERSION}" /opt/hadoop

ENV HADOOP_HOME=/opt/hadoop
ENV HADOOP_COMMON_LIB_NATIVE_DIR=/opt/hadoop/lib/native
ENV LD_LIBRARY_PATH=/opt/hadoop/lib/native
ENV SPARK_DIST_CLASSPATH=/opt/hadoop/share/hadoop/common/*:/opt/hadoop/share/hadoop/common/lib/*:/opt/hadoop/share/hadoop/hdfs/*:/opt/hadoop/share/hadoop/hdfs/lib/*:/opt/hadoop/share/hadoop/mapreduce/*:/opt/hadoop/share/hadoop/mapreduce/lib/*:/opt/hadoop/share/hadoop/yarn/*:/opt/hadoop/share/hadoop/yarn/lib/*

# Install S3A support directly into Spark's core classpath so Hadoop can load
# the AWS SDK without depending on spark.jars.packages or isolated classloaders.
RUN set -eux; \
	base_url=https://repo1.maven.org/maven2; \
	curl -fsSL "$base_url/org/apache/hadoop/hadoop-aws/${HADOOP_AWS_VERSION}/hadoop-aws-${HADOOP_AWS_VERSION}.jar" -o /opt/spark/jars/hadoop-aws-${HADOOP_AWS_VERSION}.jar; \
	curl -fsSL "$base_url/software/amazon/awssdk/bundle/${AWS_SDK_BUNDLE_VERSION}/bundle-${AWS_SDK_BUNDLE_VERSION}.jar" -o /opt/spark/jars/bundle-${AWS_SDK_BUNDLE_VERSION}.jar; \
	curl -fsSL "$base_url/software/amazon/s3/analyticsaccelerator/analyticsaccelerator-s3/${AWS_ANALYTICS_ACCELERATOR_VERSION}/analyticsaccelerator-s3-${AWS_ANALYTICS_ACCELERATOR_VERSION}.jar" -o /opt/spark/jars/analyticsaccelerator-s3-${AWS_ANALYTICS_ACCELERATOR_VERSION}.jar; \
	curl -fsSL "$base_url/org/wildfly/openssl/wildfly-openssl/${WILDFLY_OPENSSL_VERSION}/wildfly-openssl-${WILDFLY_OPENSSL_VERSION}.jar" -o /opt/spark/jars/wildfly-openssl-${WILDFLY_OPENSSL_VERSION}.jar; \
	curl -fsSL "$base_url/io/unitycatalog/unitycatalog-client/${UNITYCATALOG_VERSION}/unitycatalog-client-${UNITYCATALOG_VERSION}.jar" -o /opt/spark/jars/unitycatalog-client-${UNITYCATALOG_VERSION}.jar; \
	curl -fsSL "$base_url/io/unitycatalog/unitycatalog-spark_2.13/${UNITYCATALOG_VERSION}/unitycatalog-spark_2.13-${UNITYCATALOG_VERSION}.jar" -o /opt/spark/jars/unitycatalog-spark_2.13-${UNITYCATALOG_VERSION}.jar; \
	curl -fsSL "$base_url/io/delta/delta-spark_2.13/${DELTA_VERSION}/delta-spark_2.13-${DELTA_VERSION}.jar" -o /opt/spark/jars/delta-spark_2.13-${DELTA_VERSION}.jar; \
	curl -fsSL "$base_url/io/delta/delta-storage/${DELTA_VERSION}/delta-storage-${DELTA_VERSION}.jar" -o /opt/spark/jars/delta-storage-${DELTA_VERSION}.jar

# Install Python kernel support for Jupyter-backed workflows inside the container.
RUN pip3 install --no-cache-dir ipykernel

# Provide pyspark module for notebook kernels running in the container.
RUN pip3 install --no-cache-dir pyspark==4.1.1

# Install pandas and pyarrow for Spark Connect, plus Dagster, plus AWS CLI for STS rotation
RUN pip3 install --no-cache-dir pandas pyarrow grpcio grpcio-status zstandard dagster==1.13.2 dagster-webserver==1.13.2 dagstermill==0.29.2 papermill dagster-postgres==0.29.2 psycopg2-binary awscli uv

# Install the IPython kernel globally so Dagstermill/Papermill can find "python3"
RUN python3 -m ipykernel install --name python3 --display-name "Python 3"

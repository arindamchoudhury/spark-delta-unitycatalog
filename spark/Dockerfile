FROM apache/spark:4.1.1-scala2.13-java21-python3-ubuntu

USER root

ENV HADOOP_VERSION=3.4.3

# Install runtime dependencies for Hadoop native libs.
RUN apt-get update && apt-get install -y --no-install-recommends \
	ca-certificates \
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

# Install Python kernel support for Jupyter-backed workflows inside the container.
RUN pip3 install --no-cache-dir ipykernel

# Provide pyspark module for notebook kernels running in the container.
RUN pip3 install --no-cache-dir pyspark==4.1.1

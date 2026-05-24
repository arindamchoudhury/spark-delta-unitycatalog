# BrokenPipeError in grouped aggregate Pandas UDFs (SPARK-53609)

This document explains the `BrokenPipeError` seen when running grouped
aggregate Pandas UDFs, and why the `preview` branch compiles Spark from
`branch-4.2` source to resolve it.

- JIRA: <https://issues.apache.org/jira/browse/SPARK-53609>
- Pull request: <https://github.com/apache/spark/pull/52581>

## Symptom

```text
Traceback (most recent call last):
  File ".../python/lib/pyspark.zip/pyspark/daemon.py", line 233, in manager
    code = worker(sock, authenticated)
  File ".../python/lib/pyspark.zip/pyspark/daemon.py", line 87, in worker
    outfile.flush()
    ~~~~~~~~~~~~~^^
BrokenPipeError: [Errno 32] Broken pipe
```

The error fires while running a grouped aggregate Pandas UDF
(`SQL_GROUPED_AGG_PANDAS_UDF`), e.g. `df.groupby(...).agg(my_pandas_udf(...))`.

## What the traceback means

PySpark executes Python UDFs in worker subprocesses spawned by `daemon.py`.
Each worker:

1. reads its input rows from the JVM over a socket,
2. computes the UDF, then
3. writes results back and calls `outfile.flush()`.

`BrokenPipeError: [Errno 32] Broken pipe` on `outfile.flush()` means the **JVM
side already closed the connection** before the Python worker finished writing.
The worker is the victim, not the cause: it flushes into a pipe whose other end
is already gone.

## Root cause

For grouped aggregate Pandas UDFs, the affected versions routed the worker
through the wrong serializer — the streaming Arrow path
(`ArrowStreamAggPandasUDFSerializer`) instead of the grouped path. That
serializer's read/write protocol did not match what the JVM's
`ArrowAggregatePythonExec` expected, so the JVM reached end-of-stream early and
tore down the socket. The worker's final flush then failed.

## Why the fix touches two files

PR #52581 changes **both** sides of the protocol:

| Side | File | Change |
|------|------|--------|
| JVM | `ArrowAggregatePythonExec.scala` | Adds `GroupedPythonArrowInput` routing so the aggregate exec uses the correct grouped serializer |
| Python | `worker.py` | Matching consumer side |

A Python-only patch cannot fix this: the JVM is the side that closes the pipe
early, so the `.scala` change is required. This is why dropping a patched
`worker.py` into a prebuilt tarball does **not** work.

## Affected vs. fixed

| Build | Status |
|-------|--------|
| Spark 4.1.x prebuilt | Affected — lacks the fix |
| `v4.2.0-preview5` tag | Affected — has neither half of #52581 |
| `branch-4.2` HEAD (post-#52581) | Fixed — both JVM and Python halves present |

## How this project resolves it

The `preview` branch does **not** use a prebuilt Spark tarball. Its
`spark/Dockerfile` compiles Spark from `branch-4.2` source in a multi-stage
build, so the produced distribution includes both halves of the fix. See the
`spark-builder` stage in [`spark/Dockerfile`](spark/Dockerfile) and the
"Picking up newer branch-4.2 commits" section in [`README.md`](README.md).

## Verifying the fix

Run a minimal grouped aggregate Pandas UDF against the built image:

```python
from pyspark.sql import SparkSession
from pyspark.sql.functions import pandas_udf
import pandas as pd

spark = SparkSession.builder.remote("sc://localhost:15002").getOrCreate()

@pandas_udf("double")
def mean_udf(v: pd.Series) -> float:
    return v.mean()

df = spark.createDataFrame(
    [(1, 1.0), (1, 2.0), (2, 3.0), (2, 5.0), (2, 10.0)],
    ("id", "v"),
)
df.groupby("id").agg(mean_udf(df["v"]).alias("mean_v")).show()
```

On an affected build this raises `BrokenPipeError`. On a `branch-4.2` build it
returns the per-group means:

```text
+---+------+
| id|mean_v|
+---+------+
|  1|   1.5|
|  2|   6.0|
+---+------+
```

# Debugging a Mysterious BrokenPipeError in PySpark Pandas UDFs

*A deep dive into what causes it, why every config knob fails, and how to actually silence it*

---

I've been working through *Data Analysis with Python and PySpark* by Jonathan Rioux (Manning, 2022) and decided to build a proper local stack instead of using Databricks or a cloud cluster. The result is [spark-delta-unitycatalog](https://github.com/arindamchoudhury/spark-delta-unitycatalog): a Docker Compose environment with Spark 4.1.2, Delta Lake, Unity Catalog OSS, MinIO, and Dagster — everything wired together, running on my laptop.

For the GSOD (Global Surface Summary of Day) weather data used throughout the book, I pulled the companion dataset from [jonesberg/DataAnalysisWithPythonAndPySpark-Data](https://github.com/jonesberg/DataAnalysisWithPythonAndPySpark-Data/tree/trunk/gsod_noaa).

Everything was working fine until Chapter 9 — the chapter on pandas UDFs.

---

## Getting the stack running

Clone the repo, download the Spark dependencies, and start the stack:

```bash
git clone https://github.com/arindamchoudhury/spark-delta-unitycatalog
cd spark-delta-unitycatalog

conda env create -f environment.yml
conda activate spark-delta-uc
python download_deps.py

docker compose build spark
docker compose up -d
```

`download_deps.py` fetches the Spark tarball, Hadoop tarball, and all required jars (Delta, Unity Catalog, S3A) into `spark/tar/` and `spark/jar/` — both git-ignored. It reads version pins from `spark/Dockerfile` so there is no duplication.

Next, add the GSOD data. Clone the companion repo and copy the parquet files into `workspace/data/gsod_noaa/`:

```bash
git clone https://github.com/jonesberg/DataAnalysisWithPythonAndPySpark-Data companion-data
mkdir -p workspace/data/gsod_noaa
cp -r companion-data/gsod_noaa/. workspace/data/gsod_noaa/
```

The notebooks resolve data paths relative to `workspace/`, so `workspace/data/gsod_noaa/gsod2010.parquet` through `gsod2020.parquet` is all that is needed.

Open the repo in VS Code and run **Dev Containers: Reopen in Container** to attach to the running `spark` service. Create a new notebook under `workspace/notebooks/`, name it whatever you like, and select the **spark** kernel from the kernel picker.

---

## The problem

Start with imports and a local Spark session:

```python
from pyspark.sql import SparkSession
import pyspark.sql.functions as F
import pyspark.sql.types as T
import pandas as pd
import os

os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"
conf_path = os.path.abspath("log4j2.xml")

spark = (
    SparkSession.builder
    .appName("chapter9")
    .config("spark.ui.port", "4042")
    .config(
        "spark.driver.extraJavaOptions",
        f"-Dlog4j2.configurationFile={conf_path}"
    )
    .getOrCreate()
)
```

Read the GSOD parquet files for 2010–2020 and do basic cleaning:

```python
from functools import reduce
from pathlib import Path

data_dir = Path.cwd().parent / "data" / "gsod_noaa"

gsod = (
    reduce(
        lambda x, y: x.unionByName(y, allowMissingColumns=True),
        [
            spark.read.parquet((data_dir / f"gsod{year}.parquet").as_posix())
            for year in range(2010, 2021)
        ],
    )
    .dropna(subset=["year", "mo", "da", "temp"])
    .where(F.col("temp") != 9999.9)
    .drop("date")
)
```

Now define a grouped-agg pandas UDF that fits a per-group linear regression to measure how temperature changes across the days of a month:

```python
from sklearn.linear_model import LinearRegression

@F.pandas_udf(T.DoubleType())
def rate_of_change_temperature(day: pd.Series, temp: pd.Series) -> float:
    return (
        LinearRegression()
        .fit(X=day.astype(int).values.reshape(-1, 1), y=temp)
        .coef_[0]
    )

result = gsod.groupby("stn", "year", "mo").agg(
    rate_of_change_temperature(gsod["da"], gsod["temp"]).alias("rt_chg_temp")
)
result.show(5, False)
```

Run `result.show(5, False)` and this appeared in the notebook output — on every call:

```text
Traceback (most recent call last):
  File ".../pyspark/daemon.py", line 233, in manager
    code = worker(sock, authenticated)
  File ".../pyspark/daemon.py", line 87, in worker
    outfile.flush()
BrokenPipeError: [Errno 32] Broken pipe
```

The results were still correct. But the traceback was alarming.

---

## What's Actually Happening

PySpark runs pandas UDFs in worker subprocesses managed by `daemon.py`. After an action completes, workers sit **idle** in a pool. On the next action the daemon recycles them; a worker whose socket the JVM has already closed tries to flush its output on cleanup — and gets `BrokenPipeError: [Errno 32] Broken pipe`. Because the pool keeps turning over, the error recurs on repeated actions — in a long-lived notebook session, on essentially every `show()` after the first.

This is benign. The query has already succeeded. The flush error happens *after* results are delivered.

What changed in Spark 4.1.0 is [SPARK-54344](https://issues.apache.org/jira/browse/SPARK-54344), which introduced `spark.python.daemon.killWorkerOnFlushFailure` (default `true`). Before 4.1.0, this idle-worker recycling happened silently. Now it dumps a traceback.

In classic `local[*]` mode, the driver, executors, and Python workers all share your notebook kernel's process tree. Worker stderr goes straight to your notebook output. It can appear in the same cell as the UDF call, right after the results table — or it can bleed into a completely unrelated later cell, depending on timing.

---

## Every Config Knob Fails

Naturally I reached for configuration. Every option made things worse or had no effect:

**`spark.python.daemon.killWorkerOnFlushFailure=false`** — still prints, and now adds a `"PySpark daemon failed to flush the output to the worker process"` warning on top of the BrokenPipeError traceback. More output, not less.

**`spark.python.worker.reuse=false`** — still prints the same BrokenPipeError.

**`spark.python.use.daemon=false`** — worse. Adds `ConnectionResetError` on top of the BrokenPipeError.

This isn't a configuration problem. The root cause is in `PythonWorkerFactory.scala`. When it starts the daemon or a worker, it wires that process's stdout and stderr to the JVM's `System.err` through a helper:

```scala
private def redirectStreamsToStderr(stdout: InputStream, stderr: InputStream): Unit = {
  try {
    new RedirectThread(
      workerLogCapture.map(_.wrapInputStream(stdout)).getOrElse(stdout),
      System.err, "stdout reader for " + pythonExec).start()
    new RedirectThread(stderr, System.err, "stderr reader for " + pythonExec).start()
  // ...
}
```

Note the asymmetry: stdout is optionally wrapped by a log-capture handler, but **stderr is redirected to `System.err` unconditionally** — there's no config gate on that line. Config flags can change *what* the daemon writes to stderr, but not *where* it goes. Changing `killWorkerOnFlushFailure` just changes the message content; it still lands on `System.err`, which in local mode is your notebook's stderr.

---

## Silencing it in classic local mode

Since the problem is that the JVM's `System.err` ends up in your notebook output, the solution is to redirect OS file descriptor 2 to a log file **before** the JVM starts.

The JVM inherits fd 2 from the Python process at launch. Once `SparkSession.builder.getOrCreate()` has been called, the JVM has already captured its copy of fd 2 — redirecting it in Python afterwards does nothing for the JVM. The redirect must come first.

```python
# First cell — must run before SparkSession.builder.getOrCreate()
import os
_errfd = os.open("/tmp/spark-stderr.log", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
os.dup2(_errfd, 2)
os.close(_errfd)
```

After this, the daemon's stderr — BrokenPipeErrors and all — lands in `/tmp/spark-stderr.log`, and your notebook output stays clean. I verified this with the GSOD pipeline: three consecutive `result.show(5, False)` calls all returned correct tables to stdout with zero tracebacks, while the redirect file captured the BrokenPipeError tracebacks (Spark's stage-progress bars get redirected there too, since they also go to stderr).

**Caveats:**
- This redirects *all* JVM stderr. Any real driver-side error goes to the file too. If something breaks unexpectedly, check `/tmp/spark-stderr.log` before concluding there's no error output.
- Don't redirect to `/dev/null` — you'll silently lose genuine errors.
- `%%capture` in Jupyter doesn't help here. The async daemon flush happens after the UDF cell completes, so it arrives during a later cell's execution. Cell-level capture can't intercept it.

---

## Alternative: Spark Connect

The architectural fix is to use Spark Connect:

```python
spark = SparkSession.builder.remote("sc://localhost:15002").getOrCreate()
```

With Connect, UDF workers run inside the Spark server container. The client only receives gRPC results — it never sees worker stderr. The benign BrokenPipeError still happens, but it stays in the server's log file (`/opt/spark/logs/*.out`) and never reaches your notebook.

This is also the right pattern for production-style code. The Dagster assets in the project already use `.remote("sc://spark:15002")`, so orchestrated jobs are clean by design. The notebooks are the only place where classic local mode comes up.

One caveat: a Connect session has no local JVM gateway, so `spark.sparkContext._jvm` raises. Swap version-printing code to:

```python
print(f"Spark {spark.version}")
print(spark.sql("SELECT reflect('java.lang.System','getProperty','java.version') AS v").first()["v"])
```

---

## Summary

If you're running pandas UDFs in classic `local[*]` mode on Spark 4.1+ and seeing BrokenPipeError tracebacks after every action:

1. **It's benign.** Your query succeeded. This is idle-worker cleanup noise exposed by SPARK-54344's default `killWorkerOnFlushFailure=true`.
2. **Config flags won't silence it.** `PythonWorkerFactory` unconditionally routes worker stderr to JVM `System.err` with no config gate.
3. **To silence it in-process:** redirect fd 2 to a file as the very first cell in your notebook, before `getOrCreate()`.
4. **Better long-term:** switch to Spark Connect. Workers stay server-side; your client output is always clean.

The full stack — Spark, Delta, Unity Catalog, Dagster, MinIO — is at [github.com/arindamchoudhury/spark-delta-unitycatalog](https://github.com/arindamchoudhury/spark-delta-unitycatalog).

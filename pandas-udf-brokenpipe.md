# Benign BrokenPipeError from pandas UDFs in a long-lived session

## TL;DR

- A pandas UDF query prints a `BrokenPipeError` traceback, **but the query
  succeeds with correct results**. It is benign log noise, not a failure.
- It fires on the **second (or later) action** in a long-lived classic
  `local[*]` session: idle pandas-UDF workers from the previous action get
  recycled and a stale socket flush fails.
- In local mode those workers live in your **notebook kernel's process tree**,
  so the daemon's stderr shows up in your notebook output.
- **Not** fixed by `spark.python.daemon.killWorkerOnFlushFailure` or
  `spark.python.worker.reuse` — both were tested and still print.
- **Fixed by using Spark Connect** (`.remote("sc://…")`): UDF workers run in the
  server container, the client receives only the gRPC result stream, so output
  is clean. The benign message stays in the server log.
- This is **not** SPARK-53609 — see "Not SPARK-53609" below.

## Symptom

```text
Traceback (most recent call last):
  File ".../pyspark/daemon.py", line 233, in manager
    code = worker(sock, authenticated)
  File ".../pyspark/daemon.py", line 87, in worker
    outfile.flush()
BrokenPipeError: [Errno 32] Broken pipe
```

Appears while running a pandas UDF — e.g. the GSOD `rate_of_change_temperature`
grouped-agg — typically on a repeated or subsequent action in the same session.

## It is benign (verified)

`result.show(5, False)` returns correct rows even when the traceback prints. If
the error were fatal, `.show()` would raise instead of returning. Running the
exact same query over Spark Connect produces **identical** results with no
traceback — so the output is correct regardless of the message.

## Root cause (verified by reproduction)

PySpark runs pandas UDFs in worker subprocesses managed by `daemon.py`. After an
action completes, workers sit **idle** in the daemon pool. On the next action
they are recycled; a worker whose socket the JVM has already closed raises
`BrokenPipeError` on its cleanup `outfile.flush()` (`daemon.py` `worker()`,
line 87). Since **SPARK-54344** (Spark 4.1.0), the default
`spark.python.daemon.killWorkerOnFlushFailure=true` escalates this into a worker
kill plus a dumped traceback.

Reproduced with the exact GSOD pipeline in `local[*]` mode (real data, 2010–2020,
same cleaning and sklearn UDF):

- **First** `result.show(5, False)` → clean.
- **Second** `result.show(5, False)` → prints the `BrokenPipeError` during the
  stage, **and the query still completes** with correct output.

In local mode the driver, executors, and Python workers share the notebook
kernel's process tree, so the worker's stderr is your notebook's stderr. That is
why it surfaces in a later cell (e.g. a version-print cell that itself spawns no
UDF workers).

## What does NOT fix it (tested)

| Setting | Result |
|---------|--------|
| `spark.python.daemon.killWorkerOnFlushFailure=false` | Still prints — a `"PySpark daemon failed to flush…"` line **plus** two tracebacks (more output, not less) |
| `spark.python.worker.reuse=false` | Still prints the same `BrokenPipeError` on the second action |

Neither daemon/worker knob silences it. `killWorkerOnFlushFailure=false` only
stops the worker *kill*; the stderr noise remains.

## The fix: use Spark Connect

```python
spark = SparkSession.builder.remote("sc://localhost:15002").getOrCreate()
```

Verified: the same twice-`show` GSOD pipeline over `sc://localhost:15002`
produced **clean client output**, identical results, and the benign
`BrokenPipeError` was relegated to the server log (`/opt/spark/logs/*.out`).
With Connect, UDF workers run in the spark container under the Connect server;
the client only ever receives gRPC results, never worker stderr. This also
matches the project's architecture — the Dagster assets already use
`.remote("sc://spark:15002")`.

**Caveat:** a Connect session has no local JVM gateway, so
`spark.sparkContext._jvm` / `._gateway` raise. Replace version-print code with:

```python
print(f"Spark {spark.version}")
print(spark.sql("SELECT reflect('java.lang.System','getProperty','java.version') AS v").first()["v"])
```

## If you must stay in classic local mode

The message is unavoidable benign noise — ignore it. Confirm correctness by
comparing results against a non-UDF aggregate; they match.

## Not SPARK-53609

This was initially attributed to **SPARK-53609** ("Apply arrow batching in
`SQL_GROUPED_AGG_PANDAS_UDF`"). That is a real but **separate** correctness bug
(grouped-agg Arrow batch slicing), fixed on `branch-4.2` by PR #52581 — which is
why the `preview` branch builds Spark from `branch-4.2` source. It is **not** the
cause of this `BrokenPipeError`:

- SPARK-53609's own test (`test_arrow_batch_slicing`) was mirrored and **passed**
  on 4.1.1 — each group received its full data, so the slicing bug does not
  reproduce there.
- The `BrokenPipeError` occurs even when results are fully correct, and is
  triggered by repeated actions / idle-worker recycling, not by batch slicing.

Keep building from `branch-4.2` for the SPARK-53609 fix on its own merits, but it
is unrelated to this benign flush message.

## References

- [SPARK-54344 — Kill the worker if flush fails in daemon.py](https://issues.apache.org/jira/browse/SPARK-54344) (introduced the message; default `kill=true` since 4.1.0)
- [SPARK-47565 — PySpark workers dying in daemon idle queue](https://issues.apache.org/jira/browse/SPARK-47565)
- [SPARK-53609](https://issues.apache.org/jira/browse/SPARK-53609) / [PR #52581](https://github.com/apache/spark/pull/52581) — separate batch-slicing fix, present on `branch-4.2`

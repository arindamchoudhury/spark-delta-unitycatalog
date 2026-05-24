# Grouped aggregate Pandas UDF BrokenPipeError — investigation notes

This document tracks the `BrokenPipeError` seen when running a grouped aggregate
Pandas UDF (the GSOD `rate_of_change_temperature` example), what we have and
have **not** confirmed about its cause, and the SPARK-53609 batch-slicing fix
that motivated building Spark from `branch-4.2` source on the `preview` branch.

- JIRA: <https://issues.apache.org/jira/browse/SPARK-53609>
  (title: *"Apply arrow batching in: SQL_GROUPED_AGG_PANDAS_UDF"*)
- Pull request: <https://github.com/apache/spark/pull/52581>

## Status: root cause NOT yet confirmed

> The `BrokenPipeError` was initially attributed to **SPARK-53609**. Testing has
> **not** borne that out — see "What we verified" below. SPARK-53609 is a real
> batch-slicing bug fixed in `branch-4.2`, but it does **not** reproduce on
> 4.1.1, so it is most likely **not** the cause of the GSOD failure. Treat the
> attribution as open until the candidate causes below are tested.

## Symptom

A grouped aggregate Pandas UDF — `df.groupby(...).agg(my_pandas_udf(...))` —
fails with:

```text
Traceback (most recent call last):
  File ".../python/lib/pyspark.zip/pyspark/daemon.py", line 233, in manager
    code = worker(sock, authenticated)
  File ".../python/lib/pyspark.zip/pyspark/daemon.py", line 87, in worker
    outfile.flush()
    ~~~~~~~~~~~~~^^
BrokenPipeError: [Errno 32] Broken pipe
```

The concrete failing case is the GSOD example from *Data Analysis with Python
and PySpark* — a **two-argument** grouped-agg UDF over many small groups:

```python
result = gsod.groupby("stn", "year", "mo").agg(
    rate_of_change_temperature(gsod["da"], gsod["temp"]).alias("rt_chg_temp")
)
result.show(5, False)
```

## The BrokenPipeError is a tail symptom, not the root cause

PySpark runs Python UDFs in worker subprocesses spawned by `daemon.py`. The
worker reads input batches from the JVM over a socket, computes the UDF, and
writes results back. `BrokenPipeError` on `outfile.flush()` means the **JVM
already closed the connection** before the worker finished — usually because the
task was aborted upstream for some *other* reason (a Python exception in the
UDF, or a JVM-side error). The flush is the last thing the dying worker tries to
do; it is the symptom, not the cause. The real error is upstream and is not
visible in the snippet above.

## What we verified

A reproduction mirroring the PR's own `test_arrow_batch_slicing` (a `range`
dataset keyed by `id % 2`, a single-argument `GROUPED_AGG` UDF, with
`maxRecordsPerBatch` lowered to force many batches) **passes** on Spark 4.1.1
and returns correct per-group results:

```python
spark.conf.set("spark.sql.execution.arrow.maxRecordsPerBatch", "1000")

@pandas_udf("double")
def mean_udf(v: pd.Series) -> float:
    return v.mean()

df = spark.range(0, 200_000).selectExpr("id % 2 AS g", "CAST(id AS DOUBLE) AS v")
df.groupby("g").agg(mean_udf(col("v")).alias("mean_v")).show()
# g=0 -> 99999.0, g=1 -> 100000.0   (correct)
```

The PR's test asserts each group's UDF receives its **full** data
(`assert len(v) == 5_000_000`). Getting the exact correct means proves each
group received all its rows. **Conclusion: 4.1.1 batches grouped-agg UDFs
correctly, so SPARK-53609's slicing bug does not reproduce there** — and is
therefore unlikely to be the cause of the GSOD `BrokenPipeError`.

## Candidate causes for the GSOD failure (untested)

What differs between the passing repro and the failing GSOD case:

1. **Two-argument** grouped-agg UDF (`day, temp`) vs single-argument — a
   different code path.
2. The UDF calls **sklearn `LinearRegression`**, which *raises* on a degenerate
   group: a `(stn, year, mo)` with fewer than 2 distinct days, or NaN `temp`. A
   raised exception kills the worker → the observed `BrokenPipeError`.
3. Many tiny groups vs two large groups.

## How to diagnose it

Get the **real** upstream error, then isolate the trigger:

1. **Full error:** `docker compose logs spark` often shows the Python worker's
   actual exception (the one that precedes the `BrokenPipeError`). The
   driver-side Spark Connect exception is more informative than the `daemon.py`
   tail.
2. **Discriminating test (a) — multi-arg path:** run a *two-argument*
   grouped-agg UDF on clean synthetic data (no sklearn). If it fails, the
   multi-arg path is implicated.
3. **Discriminating test (b) — degenerate group:** guard the GSOD UDF before
   fitting:

   ```python
   @pandas_udf("double")
   def rate_of_change_temperature(day: pd.Series, temp: pd.Series) -> float:
       if day.nunique() < 2 or temp.isna().any():
           return float("nan")
       return (
           LinearRegression()
           .fit(X=day.astype(int).values.reshape(-1, 1), y=temp)
           .coef_[0]
       )
   ```

   If the error disappears, the cause was a UDF exception on a bad group — not a
   Spark bug.

## SPARK-53609 (the batch-slicing fix) for reference

Independent of the GSOD question, SPARK-53609 is a genuine bug: for grouped-agg
Pandas UDFs whose group data spans multiple Arrow batches, affected versions
sliced batches incorrectly, producing wrong aggregates. PR #52581 fixes it on
both sides of the protocol:

| Side | File | Change |
|------|------|--------|
| Python | `pyspark/worker.py` | Routes `SQL_GROUPED_AGG_PANDAS_UDF` through `GroupPandasUDFSerializer` |
| JVM | `ArrowAggregatePythonExec.scala` | Mixes in `GroupedPythonArrowInput` for correct batch slicing |

A Python-only patch cannot fix it (the JVM does the slicing), which is why the
`preview` branch compiles Spark from `branch-4.2` source — see the
`spark-builder` stage in [`spark/Dockerfile`](spark/Dockerfile) — rather than
dropping in a prebuilt tarball. Building from `branch-4.2` picks up this fix
regardless of whether it turns out to be related to the GSOD error.

"""
Backport of SPARK-54531 onto Spark 4.1.1.

Introduces ArrowStreamAggPandasUDFSerializer so that
SQL_GROUPED_AGG_PANDAS_UDF and SQL_WINDOW_AGG_PANDAS_UDF use a
dedicated serializer instead of sharing GroupPandasUDFSerializer
with SQL_GROUPED_MAP_PANDAS_UDF.

PR: https://github.com/apache/spark/pull/53239
"""

import pathlib
import sys

PYSPARK = pathlib.Path("/opt/spark/python/pyspark")


# ---------------------------------------------------------------------------
# 1. serializers.py — append new class
# ---------------------------------------------------------------------------

NEW_CLASS = '''

class ArrowStreamAggPandasUDFSerializer(ArrowStreamPandasUDFSerializer):
    """Serializer for SQL_GROUPED_AGG_PANDAS_UDF and SQL_WINDOW_AGG_PANDAS_UDF.

    Backported from SPARK-54531 (fixed in Spark 4.2.0).
    """

    def __init__(
        self,
        timezone,
        safecheck,
        assign_cols_by_name,
        int_to_decimal_coercion_enabled,
    ):
        super().__init__(
            timezone=timezone,
            safecheck=safecheck,
            assign_cols_by_name=False,
            df_for_struct=False,
            struct_in_pandas="dict",
            ndarray_as_list=False,
            arrow_cast=True,
            input_types=None,
            int_to_decimal_coercion_enabled=int_to_decimal_coercion_enabled,
        )
        self._timezone = timezone
        self._safecheck = safecheck
        self._assign_cols_by_name = assign_cols_by_name

    def load_stream(self, stream):
        """Deserialize grouped ArrowRecordBatches as a list of pandas.Series."""
        import pyarrow as pa

        dataframes_in_group = None
        while dataframes_in_group is None or dataframes_in_group > 0:
            dataframes_in_group = read_int(stream)
            if dataframes_in_group == 1:
                yield [
                    self.arrow_to_pandas(c, i)
                    for i, c in enumerate(
                        pa.Table.from_batches(
                            ArrowStreamSerializer.load_stream(self, stream)
                        ).itercolumns()
                    )
                ]
            elif dataframes_in_group != 0:
                raise PySparkValueError(
                    errorClass="INVALID_NUMBER_OF_DATAFRAMES_IN_GROUP",
                    messageParameters={
                        "dataframes_in_group": str(dataframes_in_group)
                    },
                )

    def __repr__(self):
        return "ArrowStreamAggPandasUDFSerializer"
'''

serializers_path = PYSPARK / "sql/pandas/serializers.py"
content = serializers_path.read_text()
if "ArrowStreamAggPandasUDFSerializer" in content:
    print("serializers.py: already patched, skipping")
else:
    serializers_path.write_text(content + NEW_CLASS)
    print("serializers.py: patched OK")


# ---------------------------------------------------------------------------
# 2. worker.py — add import + fix eval_type routing
# ---------------------------------------------------------------------------

worker_path = PYSPARK / "worker.py"
content = worker_path.read_text()

if "ArrowStreamAggPandasUDFSerializer" in content:
    print("worker.py: already patched, skipping")
    sys.exit(0)

# 2a. Add import alongside ArrowStreamPandasUDFSerializer
OLD_IMPORT = "    ArrowStreamPandasUDFSerializer,"
NEW_IMPORT = (
    "    ArrowStreamPandasUDFSerializer,\n"
    "    ArrowStreamAggPandasUDFSerializer,"
)
if OLD_IMPORT not in content:
    print("ERROR: could not find import anchor in worker.py", file=sys.stderr)
    sys.exit(1)
content = content.replace(OLD_IMPORT, NEW_IMPORT, 1)

# 2b. Split the combined eval_type branch so AGG/WINDOW_AGG get the new serializer
OLD_ROUTING = (
    "        elif eval_type in (\n"
    "            PythonEvalType.SQL_GROUPED_MAP_PANDAS_UDF,\n"
    "            PythonEvalType.SQL_GROUPED_AGG_PANDAS_UDF,\n"
    "            PythonEvalType.SQL_WINDOW_AGG_PANDAS_UDF,\n"
    "        ):"
)
NEW_ROUTING = (
    "        elif eval_type in (\n"
    "            PythonEvalType.SQL_GROUPED_AGG_PANDAS_UDF,\n"
    "            PythonEvalType.SQL_WINDOW_AGG_PANDAS_UDF,\n"
    "        ):\n"
    "            ser = ArrowStreamAggPandasUDFSerializer(\n"
    "                timezone, safecheck, _assign_cols_by_name,"
    " int_to_decimal_coercion_enabled\n"
    "            )\n"
    "        elif eval_type == PythonEvalType.SQL_GROUPED_MAP_PANDAS_UDF:"
)
if OLD_ROUTING not in content:
    print("ERROR: could not find routing anchor in worker.py", file=sys.stderr)
    print("The worker.py structure may differ — manual inspection needed.",
          file=sys.stderr)
    sys.exit(1)
content = content.replace(OLD_ROUTING, NEW_ROUTING, 1)

worker_path.write_text(content)
print("worker.py: patched OK")


# ---------------------------------------------------------------------------
# 3. pyspark.zip — update both patched files so worker processes (which Spark
#    launches with pyspark.zip first on PYTHONPATH) see the same patches.
# ---------------------------------------------------------------------------

import zipfile

zip_path = PYSPARK.parent / "lib" / "pyspark.zip"
with zipfile.ZipFile(zip_path, "a") as zf:
    zf.write(serializers_path, "pyspark/sql/pandas/serializers.py")
    zf.write(worker_path, "pyspark/worker.py")
print("pyspark.zip: updated OK")

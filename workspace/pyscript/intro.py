"""
Word Count — Hello World for Distributed Computing
===================================================
Counts the most frequent words in Pride and Prejudice (Project Gutenberg).

spark-submit usage
------------------
Local mode (no cluster required):
    spark-submit --master "local[*]" intro.py

Against the Docker stack (from the project root):
    docker compose exec spark spark-submit \
        --master "local[*]" \
        /workspace/pyscript/intro.py

To see the Spark UI while running (local mode binds to port 4041):
    open http://localhost:4041 in a browser while the job is running.
"""

import os
import sys
from pathlib import Path

from pyspark.sql import SparkSession
import pyspark.sql.functions as F

# ── Session setup ──────────────────────────────────────────────────────────────

# Resolve paths relative to this script's location so spark-submit works
# regardless of the working directory it is invoked from.
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_FILE  = SCRIPT_DIR / ".." / "data" / "gutenberg_books" / "1342-0.txt"
LOG4J_CONF = SCRIPT_DIR / "log4j2.xml"

os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"

spark = (
    SparkSession.builder
    .appName("word-count")
    .config("spark.ui.port", "4041")
    .config(
        "spark.driver.extraJavaOptions",
        f"-Dlog4j2.configurationFile={LOG4J_CONF}",
    )
    .getOrCreate()
)

print(
    f"Spark {spark.version} · "
    f"Java {spark.sparkContext._jvm.java.lang.System.getProperty('java.version')} · "
    f"Python {sys.version.split()[0]}"
)

# ── Read ───────────────────────────────────────────────────────────────────────

# spark.read.text() is lazy — the file is not read until an action fires.
book = spark.read.text(str(DATA_FILE))

# ── Transform (all lazy) ───────────────────────────────────────────────────────

top_words = (
    book
    .select(F.explode(F.split("value", " ")).alias("word"))    # one word per row
    .select(
        F.lower(F.regexp_extract("word", "[a-z]+", 0))         # lowercase + strip punctuation
         .alias("word")
    )
    .filter(F.col("word") != "")                               # drop empty strings
    .groupBy("word")
    .count()
    .orderBy(F.col("count").desc())
)

# ── Action ─────────────────────────────────────────────────────────────────────

# .show(10) is the first action — Spark executes the full plan here.
top_words.show(10)

# Optional: show the physical plan Spark built
# top_words.explain()

spark.stop()

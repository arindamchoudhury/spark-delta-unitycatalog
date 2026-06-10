"""
Word Count — Hello World for Distributed Computing
===================================================
Counts the most frequent words in Pride and Prejudice (Project Gutenberg).

To run intro.py with spark-submit:

    # Local mode — no cluster required, uses all available CPU cores
    SPARK_CONNECT_MODE=0 spark-submit --master "local[*]" workspace/pyscript/intro.py

    # Against the Docker stack — submit inside the spark container
    docker compose exec spark env SPARK_CONNECT_MODE=0 spark-submit \\
        --master "local[*]" \\
        /workspace/pyscript/intro.py

To run with Connect mode (Docker stack already running):
    docker compose exec spark python /workspace/pyscript/intro.py

While the job runs, the Spark UI is available at http://localhost:4040
(or 4041/4042 if 4040 is already taken by the Connect server).
"""

import sys
from pathlib import Path
import os

from pyspark.sql import SparkSession
import pyspark.sql.functions as F

# ── Session setup ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_FILE  = SCRIPT_DIR / ".." / "data" / "gutenberg_books" / "1342-0.txt"

os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"
conf_path = str(SCRIPT_DIR / "log4j2.xml")

spark = (
    SparkSession.builder
    .config("spark.ui.port", "4041")
    .config(
        "spark.driver.extraJavaOptions",
        f"-Dlog4j2.configurationFile={conf_path}",
    )
    .appName("word-count")
    .getOrCreate()
)

print(f"Spark {spark.version} · Python {sys.version.split()[0]}")

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

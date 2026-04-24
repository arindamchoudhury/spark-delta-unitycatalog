from dagster import asset
from pyspark.sql import SparkSession


@asset
def my_first_spark_asset():
    spark = SparkSession.builder.remote("sc://spark:15002").getOrCreate()
    catalogs = spark.sql("SHOW CATALOGS").collect()
    return [row.catalog for row in catalogs]


@asset
def raw_elements_table():
    spark = SparkSession.builder.remote("sc://spark:15002").getOrCreate()

    df = spark.read.option("header", "true").csv(
        "/workspace/data/elements/Periodic_Table_Of_Elements.csv"
    )

    spark.sql("DROP TABLE IF EXISTS unity.default.raw_elements")
    df.write.format("delta").save("s3a://warehouse/raw_elements")
    spark.sql(
        "CREATE EXTERNAL TABLE IF NOT EXISTS unity.default.raw_elements USING DELTA LOCATION 's3a://warehouse/raw_elements'"
    )

    return [
        row
        for row in spark.sql(
            "SELECT COUNT(*) FROM unity.default.raw_elements"
        ).collect()
    ]


@asset(deps=[raw_elements_table])
def summarized_elements_table():
    spark = SparkSession.builder.remote("sc://spark:15002").getOrCreate()

    df = spark.table("unity.default.raw_elements")
    summary_df = df.groupBy("Phase").count()

    spark.sql("DROP TABLE IF EXISTS unity.default.elements_summary")
    summary_df.write.format("delta").save("s3a://warehouse/elements_summary")
    spark.sql(
        "CREATE EXTERNAL TABLE IF NOT EXISTS unity.default.elements_summary USING DELTA LOCATION 's3a://warehouse/elements_summary'"
    )

    return [
        row
        for row in spark.sql("SELECT * FROM unity.default.elements_summary").collect()
    ]

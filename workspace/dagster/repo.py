from dagster import asset, Definitions, define_asset_job, ScheduleDefinition
from dagstermill import define_dagstermill_asset, local_output_notebook_io_manager
from pyspark.sql import SparkSession


@asset
def my_first_spark_asset():
    """A simple Dagster asset that uses the configured PySpark session."""
    # Use Spark Connect to run the job on the remote spark container
    spark = SparkSession.builder.remote("sc://spark:15002").getOrCreate()

    # Run a simple query to verify Unity Catalog connectivity
    catalogs = spark.sql("SHOW CATALOGS").collect()

    return [row.catalog for row in catalogs]


@asset
def raw_elements_table():
    """Reads the periodic table CSV file and saves it as a Delta table in Unity Catalog."""
    # Connect to the Spark Connect Server on port 15002
    spark = SparkSession.builder.remote("sc://spark:15002").getOrCreate()

    # Read the CSV from the local mounted directory
    df = spark.read.option("header", "true").csv(
        "/workspace/data/elements/Periodic_Table_Of_Elements.csv"
    )

    # Write to Unity Catalog as an EXTERNAL Delta table
    # The OSS Unity Catalog right now requires passing a LOCATION for tables if managed isn't enabled
    spark.sql("DROP TABLE IF EXISTS unity.default.raw_elements")
    df.write.format("delta").option("path", "/tmp/uc/raw_elements").saveAsTable(
        "unity.default.raw_elements"
    )

    return [
        row
        for row in spark.sql(
            "SELECT COUNT(*) FROM unity.default.raw_elements"
        ).collect()
    ]


@asset(deps=[raw_elements_table])
def summarized_elements_table():
    """Reads the raw Delta table, summarizes it, and saves a new Delta table."""
    spark = SparkSession.builder.remote("sc://spark:15002").getOrCreate()

    # Read the raw table we just created from UC
    df = spark.table("unity.default.raw_elements")

    # Group by Element Phase (solid, liquid, gas)
    summary_df = df.groupBy("Phase").count()

    # Save the summarized data as a new table
    spark.sql("DROP TABLE IF EXISTS unity.default.elements_summary")
    summary_df.write.format("delta").option(
        "path", "/tmp/uc/elements_summary"
    ).saveAsTable("unity.default.elements_summary")

    return [
        row
        for row in spark.sql("SELECT * FROM unity.default.elements_summary").collect()
    ]


# Create a job that materializes all assets
elements_job = define_asset_job(name="process_elements_job", selection="*")

# Create a schedule that runs the job every day at midnight
elements_schedule = ScheduleDefinition(
    job=elements_job,
    cron_schedule="0 0 * * *",
)

# Define an asset from a Jupyter Notebook using dagstermill
notebook_asset = define_dagstermill_asset(
    name="my_notebook_job",
    notebook_path="/workspace/notebooks/my_notebook_job.ipynb",
    save_notebook_on_failure=True,
)

# Define a job for the notebook
notebook_job = define_asset_job(
    name="process_notebook_job", selection="my_notebook_job"
)

# Define a schedule for the notebook job
notebook_schedule = ScheduleDefinition(
    job=notebook_job,
    cron_schedule="0 1 * * *",
)

defs = Definitions(
    assets=[
        my_first_spark_asset,
        raw_elements_table,
        summarized_elements_table,
        notebook_asset,
    ],
    schedules=[elements_schedule, notebook_schedule],
    jobs=[elements_job, notebook_job],
    resources={
        "output_notebook_io_manager": local_output_notebook_io_manager,
    },
)

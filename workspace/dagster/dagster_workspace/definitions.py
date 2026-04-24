from dagster import Definitions, define_asset_job, ScheduleDefinition
from dagstermill import define_dagstermill_asset, local_output_notebook_io_manager

from dagster_workspace.defs.assets import (
    my_first_spark_asset,
    raw_elements_table,
    summarized_elements_table,
)


elements_job = define_asset_job(name="process_elements_job", selection="*")

elements_schedule = ScheduleDefinition(
    job=elements_job,
    cron_schedule="0 0 * * *",
)

notebook_asset = define_dagstermill_asset(
    name="my_notebook_job",
    notebook_path="/workspace/notebooks/my_notebook_job.ipynb",
    save_notebook_on_failure=True,
)

notebook_job = define_asset_job(
    name="process_notebook_job", selection="my_notebook_job"
)

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

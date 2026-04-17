# spark-delta-unitycatalog Local Stack

This project wires together:

- Apache Spark 4.1.1 (Scala 2.13, Java 21, Python, Ubuntu image)
- Delta Lake (Spark extension + connector)
- Unity Catalog OSS server

The stack runs with Docker Compose and uses a shared mounted path (`/tmp/uc`) so
Spark can read Delta table locations registered in Unity Catalog.

Persistent data is stored on the host under `./metadata`, not in Docker
named volumes. That means your catalog data and Spark dependency cache remain on
disk even if you remove containers or rebuild the stack.

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- The local Hadoop archive must exist at `./spark/tar/hadoop-3.4.3.tar.gz`
- Internet access on first Spark SQL run if Maven packages are not already cached in `./metadata/ivy`

## Start the stack

```bash
docker compose up -d
```

The Unity Catalog UI is available at `http://localhost:3000`.
Spark UI is exposed on `http://localhost:4040` while a Spark application is running
(Spark may move to `4041`/`4042` if those ports are already in use).

## Validate Unity Catalog is reachable

```bash
curl http://localhost:8080/api/2.1/unity-catalog/catalogs
```

You should see JSON output listing catalogs (for example, `unity`).

## Run Spark SQL against Unity Catalog

```bash
docker compose exec spark /opt/spark/bin/spark-sql -f /opt/spark/scripts/smoke-test.sql
```

The SQL file is mounted from `./scripts/smoke-test.sql` and checks that Spark
can list and query Unity Catalog tables.

If you get package download errors, re-run once network access is available.
On first run, Spark downloads dependency jars; after that they are reused from
the persistent host directory `./metadata/ivy`.

## Hadoop native library support

The Spark image in `spark/Dockerfile` includes Hadoop native binaries under
`/opt/hadoop/lib/native` from the local archive `./spark/tar/hadoop-3.4.3.tar.gz`
and exports `LD_LIBRARY_PATH` so Hadoop can load
`libhadoop.so`.

If you changed the Dockerfile, rebuild the `spark` image:

```bash
docker compose build spark
docker compose up -d
```

Then verify from inside the container:

```bash
python3 - <<'PY'
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
jvm = spark.sparkContext._jvm
print("Native loaded:", jvm.org.apache.hadoop.util.NativeCodeLoader.isNativeCodeLoaded())
PY
```

## Run an interactive Spark SQL shell

```bash
docker compose exec spark /opt/spark/bin/spark-sql
```

Then try:

```sql
CREATE TABLE IF NOT EXISTS unity.default.smoke_delta (id INT, note STRING)
USING DELTA
LOCATION '/tmp/uc/smoke_delta';

DELETE FROM unity.default.smoke_delta;

INSERT INTO unity.default.smoke_delta VALUES (1, 'ok');
SELECT * FROM unity.default.smoke_delta;
```

## Stop and clean up

```bash
docker compose down -v
```

This removes containers and networks, but the data under `./metadata`
stays on disk because it is bind-mounted from the host.

If you want to stop the stack without removing containers, use:

```bash
docker compose stop
```

If you want to fully reset the local catalog and Spark cache, delete the host
folders under `./metadata/uc` and `./metadata/ivy`.

## Work with the stack from VS Code

- Open the repo locally in VS Code and use the browser for the UI on `http://localhost:3000` and the API on `http://localhost:8080`.
- Run `Tasks: Run Task` and use `compose: up`, `compose: down`, `compose: down -v`, `spark: smoke test`, or `ui: logs` from `.vscode/tasks.json`.
- Open `unitycatalog.http` and use the REST Client extension to call the local Unity Catalog API directly from the editor.
- If you want an in-container VS Code session, run `Dev Containers: Reopen in Container`. The `.devcontainer/devcontainer.json` file attaches VS Code to the running `spark` service while starting `unitycatalog` and `ui` alongside it.

## Notes

- This setup is for local experimentation, not production.
- The Spark container runs as root to simplify write access on the shared host directory mounted at `/tmp/uc`.
- For a production-like setup, replace the shared local path with S3/ADLS/GCS and configure Unity Catalog storage credentials and external locations.

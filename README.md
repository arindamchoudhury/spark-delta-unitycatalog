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
- Internet access on first Spark image build (to download baked dependency jars)

## Start the stack

```bash
docker compose up -d
```

The Unity Catalog UI is available at `http://localhost:3000`.
Dagster UI is available at `http://localhost:3001`.
Spark UI is exposed on `http://localhost:4040` while a Spark application is running
(Spark may move to `4041`/`4042` if those ports are already in use).
Spark History Server is exposed on `http://localhost:18080` and shows completed
applications from persisted event logs.
Dagster gRPC code server runs internally on port `4000`.

During startup, the one-shot `uc-rotate` service runs `scripts/rotate_uc_sts.py`
against MinIO, writes fresh STS credentials into `uc-conf/server.properties`, and
only then allows `unitycatalog` to start.

## Validate Unity Catalog is reachable

```bash
curl http://localhost:8080/api/2.1/unity-catalog/catalogs
```

You should see JSON output listing catalogs (for example, `unity`).

## Unity Catalog server configuration

Unity Catalog now loads configuration from `./uc-conf/server.properties` via a
directory mount to `/home/unitycatalog/etc/conf`.

Notes:

- Keep `uc-conf/server.properties` as the source-of-truth config file.
- Unity Catalog generates key/token artifacts in the same directory at runtime;
	these generated files are ignored by git.
- Temporary MinIO STS credentials are rotated automatically during
	`docker compose up` by the `uc-rotate` service.

If you need to inspect credential vending directly:

```bash
curl -sS -X POST http://localhost:8080/api/2.1/unity-catalog/temporary-path-credentials \
	-H 'Content-Type: application/json' \
	-d '{"url":"s3://warehouse/smoke_delta","operation":"PATH_CREATE_TABLE"}'
```

### Rotate MinIO STS credentials manually

For normal local startup, no manual action is required. `docker compose up -d`
already runs `uc-rotate` before Unity Catalog starts.

Use manual rotation only if credentials expire while the stack is already up, or
if you want to refresh `uc-conf/server.properties` without recreating the whole
stack.

Use AWS CLI against MinIO STS to mint temporary credentials, then write them to
`uc-conf/server.properties`.

1. Export the long-lived MinIO user credentials:

```bash
export AWS_ACCESS_KEY_ID=admin
export AWS_SECRET_ACCESS_KEY=password
export AWS_DEFAULT_REGION=us-east-1
```

2. Request temporary STS credentials:

```bash
aws --endpoint-url http://localhost:9000 sts assume-role \
	--role-arn arn:aws:iam::minio:user/admin \
	--role-session-name uc-session-$(date +%s) \
	--duration-seconds 3600 \
	--output json > /tmp/minio-sts.json
```

3. Extract values (for update + validation):

```bash
ACCESS_KEY=$(python3 -c "import json;print(json.load(open('/tmp/minio-sts.json'))['Credentials']['AccessKeyId'])")
SECRET_KEY=$(python3 -c "import json;print(json.load(open('/tmp/minio-sts.json'))['Credentials']['SecretAccessKey'])")
SESSION_TOKEN=$(python3 -c "import json;print(json.load(open('/tmp/minio-sts.json'))['Credentials']['SessionToken'])")
EXPIRES_AT=$(python3 -c "import json;print(json.load(open('/tmp/minio-sts.json'))['Credentials']['Expiration'])")
echo "STS expires at: $EXPIRES_AT"
```

4. Validate credentials can access MinIO:

```bash
AWS_ACCESS_KEY_ID="$ACCESS_KEY" \
AWS_SECRET_ACCESS_KEY="$SECRET_KEY" \
AWS_SESSION_TOKEN="$SESSION_TOKEN" \
aws --endpoint-url http://localhost:9000 s3 ls s3://warehouse
```

5. Update these keys in `uc-conf/server.properties`, then restart Unity Catalog:

- `s3.accessKey.0`
- `s3.secretKey.0`
- `s3.sessionToken.0`

```bash
docker compose up -d unitycatalog
```

If STS credentials expire while the stack is running, repeat the steps above and
restart Unity Catalog.

For one-command rotation, use:

```bash
python3 scripts/rotate_uc_sts.py
```

To rerun the same automation through Docker Compose, use:

```bash
docker compose run --rm uc-rotate
docker compose up -d unitycatalog
```

Useful options:

```bash
python3 scripts/rotate_uc_sts.py --no-restart
python3 scripts/rotate_uc_sts.py --no-validate
python3 scripts/rotate_uc_sts.py --duration-seconds 7200 --bucket warehouse
```

## Run Spark SQL against Unity Catalog

```bash
docker compose exec spark /opt/spark/bin/spark-sql -f /opt/spark/scripts/smoke-test.sql
```

The SQL file is mounted from `./scripts/smoke-test.sql` and checks that Spark
can list and query Unity Catalog tables.

## Spark History Server

This stack enables Spark event logging and runs a dedicated History Server:

- Event logs are written to `./metadata/spark-events`.
- History UI is available at `http://localhost:18080`.

To verify completed applications are visible:

```bash
curl -sS http://localhost:18080/api/v1/applications
```

If you get image build download errors, re-run once network access is available.
The Spark image now bakes in the S3A/Hadoop AWS jars, Unity Catalog connector jars,
and Delta Lake jars so Spark SQL does not need runtime Maven resolution.

## Hadoop native library support

The Spark image in `spark/Dockerfile` includes Hadoop native binaries under
`/opt/hadoop/lib/native` from the local archive `./spark/tar/hadoop-3.4.3.tar.gz`
and exports `LD_LIBRARY_PATH` so Hadoop can load
`libhadoop.so`.

If you changed the Dockerfile or any baked-in dependency versions, rebuild the `spark` image:

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

After a full reset, if catalogs are empty, create the default namespace objects:

```bash
curl -sS -X POST http://localhost:8080/api/2.1/unity-catalog/catalogs \
	-H 'Content-Type: application/json' \
	-d '{"name":"unity","comment":"Local default catalog","storage_root":"s3://warehouse"}'

curl -sS -X POST http://localhost:8080/api/2.1/unity-catalog/schemas \
	-H 'Content-Type: application/json' \
	-d '{"name":"default","catalog_name":"unity","comment":"Default schema"}'
```

## Work with the stack from VS Code

- Open the repo locally in VS Code and use the browser for the UI on `http://localhost:3000` and the API on `http://localhost:8080`.
- Run `Tasks: Run Task` and use `compose: up`, `compose: down`, `compose: down -v`, `spark: smoke test`, or `ui: logs` from `.vscode/tasks.json`.
- Open `unitycatalog.http` and use the REST Client extension to call the local Unity Catalog API directly from the editor.
- If you want an in-container VS Code session, run `Dev Containers: Reopen in Container`. The `.devcontainer/devcontainer.json` file attaches VS Code to the running `spark` service while starting `unitycatalog` and `ui` alongside it.

## Notes

- This setup is for local experimentation, not production.
- The Spark container runs as root to simplify write access on the shared host directory mounted at `/tmp/uc`.
- For a production-like setup, replace the shared local path with S3/ADLS/GCS and configure Unity Catalog storage credentials and external locations.
- Notebooks in `workspace/notebooks/` are git-ignored except for `intro.ipynb`. Other `.ipynb` files can be used locally but are not tracked.

## Services

- `uc-rotate`: A one-shot helper that refreshes MinIO STS credentials in `uc-conf/server.properties` before Unity Catalog starts.
- `unitycatalog`: The open source Unity Catalog server running on port `8080`.
- `ui`: The Unity Catalog UI running on port `3000`.
- `spark`: The PySpark 4.1.1 execution environment running a Spark Connect server on port `15002`.
- `spark-history`: Dedicated Spark History Server running on port `18080` for event log visualization.
- `dagster-webserver`: Dagster web UI running on port `3001` serving the control plane.
- `dagster-daemon`: Dagster daemon process handling schedules, sensors, and run queue coordination.
- `dagster-user-code`: Dagster gRPC code server on port `4000` hosting user-defined assets and jobs.

## Orchestration (Dagster & Spark Connect)

This project uses **Dagster** to schedule and orchestrate Spark jobs following the OSS Dagster Docker deployment architecture. Instead of running heavy JVM PySpark workloads inside the Dagster orchestrator, we employ **Spark Connect** to enforce separation of concerns:

### Dagster Architecture

The Dagster deployment is split into three long-running services aligned with Dagster OSS best practices:

1. **Webserver** (`dagster-webserver`): Serves the UI and GraphQL API on port `3001`.
   - Loads code locations from the gRPC code server.
   - Receives runs submitted by users.

2. **Daemon** (`dagster-daemon`): Processes schedules, sensors, and the run queue.
   - Dequeues runs from Postgres and launches them via DockerRunLauncher.
   - Can access Docker socket to spawn isolated run containers.
   - Mounts host Docker socket: `/var/run/docker.sock:/var/run/docker.sock`.

3. **User Code Server** (`dagster-user-code`): gRPC server on port `4000` hosting asset definitions.
   - Runs the `dagster_workspace` package containing assets, jobs, and schedules.
   - Accessible over the network to webserver and daemon.

### Run Execution

- **Queued coordinator** is enabled in `workspace/dagster/dagster.yaml`:
  - Runs submitted from the UI are enqueued in Postgres.
  - Daemon dequeues and launches them.

- **DockerRunLauncher** is configured:
  - Each submitted run spawns a dedicated ephemeral container using the `dagster-user-code` image.
  - Run containers share the Spark, MinIO, and Unity Catalog access paths via bind mounts.
  - Logs are persisted in Postgres for UI inspection.

### Asset Execution

When assets materialize (via schedule or manual trigger):

1. Daemon dequeues the run.
2. Daemon launches a run container with `dagster_workspace.definitions`.
3. Asset code executes in the run container.
4. Asset code initializes a remote Spark session: `SparkSession.builder.remote("sc://spark:15002").getOrCreate()`.
5. Spark operations execute in the `spark` container with full Unity Catalog access.
6. Results persist to MinIO and catalog metadata updates to Unity Catalog.

### Configuration

The Dagster stack is configured via `workspace/dagster/`:

- `pyproject.toml`: Pinned Dagster 1.13.2 + companions (dagster-postgres, dagster-docker).
- `dagster.yaml`: Instance configuration with Postgres storage, QueuedRunCoordinator, and DockerRunLauncher.
- `workspace.yaml`: Points webserver/daemon to gRPC code server.
- `dagster_workspace/definitions.py`: Exports asset definitions, jobs, and schedules.

To use the Dagster UI, visit `http://localhost:3001`.

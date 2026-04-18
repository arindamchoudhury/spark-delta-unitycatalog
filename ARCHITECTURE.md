# Modern Data Engineering Local Architecture

This project provides a robust, containerized, and production-like sandbox environment for modern Data Engineering. The architecture closely replicates what you would build in a hyperscale cloud environment (like Databricks, AWS, Azure, or GCP).

---

## 1. Current Architecture Components

The environment currently contains the following core pillars of a modern data stack:

*   **Execution Engine (Apache Spark):** 
    *   Powered by a dedicated Spark container executing Python scripts via the **Spark Connect** protocol. This enforces separation between the scheduler and the executor, matching real-world distributed execution.
*   **Storage Format (Delta Lake):** 
    *   Data is stored using open-source Delta Lake, ensuring ACID transactions, time travel, and scalable metadata handling.
*   **Data Catalog & Governance (Unity Catalog):** 
    *   A central metastore and governance layer. Unity Catalog manages the tables and namespaces, meaning Spark queries simply reference `unity.default.table_name` rather than direct file paths. Includes a dedicated web UI.
*   **Orchestration & Scheduling (Dagster):** 
    *   A modern, data-aware orchestrator. It executes asset-based DAGs and schedules workloads.
    *   Backed by **PostgreSQL**, ensuring robust run histories, event logs, and scheduler tracking.
*   **Notebook Execution (Papermill/Dagstermill):** 
    *   Jupyter notebooks can be written interactively and then scheduled directly as production assets using the Dagstermill integration.

---

## 2. Potential Architectural Improvements

While the current setup is excellent for learning and developing PySpark/Delta workloads locally, the following additions would make it a "perfect" replica of a hyperscale cloud data stack.

### 2.1 Object Storage Layer (MinIO / S3 Simulation) (COMPLETED BASELINE)
*   **Current State:** MinIO is fully integrated for local S3-compatible storage, and Spark + Delta + Unity Catalog are operating end-to-end against `s3://warehouse`.
*   **What Changed:**
    1. Spark image now bakes required S3A/AWS, Unity Catalog, and Delta jars, avoiding runtime dependency resolution and classloader conflicts.
    2. Unity Catalog is configured via `uc-conf/server.properties` and mounted as a directory to `/home/unitycatalog/etc/conf`.
    3. Temporary credentials are successfully vended from Unity Catalog (`/temporary-path-credentials`) for MinIO-backed paths.
*   **Operational Notes:**
    1. STS credentials are temporary and must be rotated before expiration.
    2. If Unity Catalog metadata is reset, recreate catalog `unity` and schema `default` before running smoke tests.

### 2.2 Interactive Notebook Server (JupyterLab)
*   **Current State:** Notebooks are scheduled in the background via Papermill, but must be authored in an external IDE (like VS Code).
*   **The Improvement:** Add a dedicated `jupyterlab` container service (using the same underlying PySpark image) bound to a local port (e.g., `8888`).
*   **Why do it?** It provides a persistent, dedicated web UI for interactive data exploration, visualization, and rapid prototyping against the Unity Catalog before converting code into Dagster assets.

### 2.3 Spark History Server
*   **Current State:** The live Spark UI is available on port `4040` only while a job is actively running. Once the Dagster job finishes, the Spark container UI stops serving that job's statistics.
*   **The Improvement:** Configure Spark to log events to a mounted directory (`spark.eventLog.enabled=true`) and spin up a separate **Spark History Server** container to serve the UI for completed jobs.
*   **Why do it?** Crucial for debugging performance bottlenecks, analyzing DAG execution plans, and understanding memory spillage on jobs that have already finished running.
# CodePathfinder Troubleshooting Guide

This guide provides an overview of the system architecture and practical steps for troubleshooting issues with the CodePathfinder application, particularly focusing on the job execution environment (Docker and Kubernetes).

## 1. System Architecture

CodePathfinder consists of several interconnected components:

*   **Django Web App (`web`)**: The core application that handles HTTP requests, the UI, and API. It is the "brain" that orchestrates everything.
*   **PostgreSQL (`db`)**: The primary relational database used by Django to store users, projects, and application state.
*   **Elasticsearch**: The search engine where code chunks and symbols are indexed for fast retrieval.
*   **Indexer Jobs**: Ephemeral processes that run the heavy logic of analyzing code repositories. These are spun up on-demand when you click "Run".

### Execution Modes

There are two ways the Indexer Jobs run, depending on your environment:

1.  **Kubernetes (Production/Cloud)**: The web app uses the Kubernetes API to launch a `Job`. This Job creates a `Pod` (a container wrapper) to run the indexer.
2.  **Local Docker (Development)**: When running locally with Docker Compose, the web app detects this and instead uses the Docker Socket (`/var/run/docker.sock`) to launch a sibling Docker container side-by-side with the web app.

**Key Concept**: The web app *must* have permission to talk to the cluster manager (K8s) or the Docker daemon to create these new processes.

## 2. Docker and Kubernetes Concepts

### Containers (Docker)
Think of a container as a lightweight, standalone package of software that includes everything needed to run: code, runtime, system tools, system libraries, and settings.
*   **Live**: A running process.
*   **Exited**: A process that finished (either success or failure).

### Pods (Kubernetes)
A Pod is the smallest deployable unit in Kubernetes. It wraps one or more containers. In our case, one Indexer Job = One Pod.
*   **Pending**: The Pod is waiting for resources (CPU/RAM) or to be scheduled.
*   **Running**: The actual code is executing.
*   **Completed/Failed**: The job finished.

## 3. Workflow: How a Job Starts

1.  **User Trigger**: You click "Run" in the UI.
2.  **Status Change**: Project status updates to `Running`.
3.  **Job Launch**:
    *   **K8s Mode**: Django reads `kubeconfig` and sends a "Create Job" request to the K8s API server.
    *   **Docker Mode**: Django connects to the local Docker daemon and sends a "Run Container" command.
4.  **Execution**: The new container starts, pulls the git repo, analyzes code, and pushes data to Elasticsearch.
5.  **Monitoring**: The web app polls the status of this job/container and fetches its logs to display in the Web Console.
6.  **Completion**: When the process exits, Django detects the exit code (0 for success) and updates the project status.

## 4. Troubleshooting Steps

If a job fails to start, gets stuck, or shows errors, follow these steps.

### Step 1: Check the Web Console
The in-app console (bottom of the project list) is your first line of defense.
*   **"Waiting for indexer logs..."**: The job hasn't started yet, or the web app can't find the container/pod.
*   **[INFO]**: Normal progress.
*   **[ERROR]**: Application-level errors (e.g., "Git authentication failed", "Elasticsearch unreachable").

### Step 2: Check Local Docker Containers (Development)
If you are running locally and the console says nothing, check the backend.

**View Running Containers:**
```bash
docker ps
```
Look for a container named like `indexer-job-<id>-<timestamp>`.

**View All Containers (including crashed ones):**
This is critical. If a job fails instantly, it won't show in `docker ps`.
```bash
docker ps -a
```
Look for containers with status `Exited (1)` or `Exited (127)`.

**Inspect Container Logs:**
If you find a crashed container ID (e.g., `a1b2c3d4`), read its internal crash logs:
```bash
docker logs a1b2c3d4
```
*   **Exit Code 127**: "Command not found". Usually means the Docker image is built incorrectly or the command passed is wrong.
*   **Exit Code 137**: "OOMKilled". Ran out of memory.
*   **Exit Code 1**: Application crash. Read the python/node traceback in the logs.

**Verify Network:**
The indexer needs to talk to the database and Elasticsearch. Ensure they are on the same network:
```bash
docker network ls
# Inspect the network to see connected containers
docker network inspect pathfinder_default
```

### Step 3: Check Web App Logs
If the job *never* appears in `docker ps`, the web app failed to launch it. Check the web app's own logs:

1.  Find the web container name:
    ```bash
    docker ps --filter "name=web"
    ```
2.  Tail the logs:
    ```bash
    docker logs -f pathfinder-web-1
    ```
    *   Look for python exceptions like `DockerException`, `ReadTimeout`, or `FileNotFoundError`.

### Step 4: Common Issues & Fixes

**Issue: "Network not found"**
*   **Cause**: The code is trying to attach the job to a network name that doesn't exist.
*   **Fix**: Run `docker network ls` to find the real name, and update `utils.py`.

**Issue: Web App crashes with Exit 127**
*   **Cause**: A volume mount in `docker-compose.yml` is trying to mount a file that doesn't exist, and Docker creates a directory instead, confusing the app.
*   **Fix**: Remove the bad volume mount line in `docker-compose.yml` and delete the accidental directory.

**Issue: App tries to use Kubernetes locally**
*   **Cause**: The presence of a `kubeconfig.yaml` file in the app directory tricks the system.
*   **Fix**: Rename or remove `apps/web/kubeconfig.yaml` to force fallback to Docker mode.

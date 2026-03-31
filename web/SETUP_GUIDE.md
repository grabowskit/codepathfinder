# CodePathfinder Setup & Administration Guide

This document provides a comprehensive guide to setting up, configuring, and maintaining the CodePathfinder application and its underlying Semantic Code Search utility.

## 1. Architecture Overview

CodePathfinder is designed as a hybrid web application that orchestrates long-running indexing tasks as ephemeral Kubernetes Jobs.

### System Components
-   **Web Backend (Django)**: Handles user authentication, project management, and search queries. It acts as the controller for indexing jobs.
-   **Semantic Indexer (CLI)**: A Node.js-based command-line utility that analyzes codebases and generates semantic embeddings. Runs as a Kubernetes Job.
-   **Shared Storage (PVC)**: A Persistent Volume Claim used to share the generated index files between the ephemeral Indexer Jobs and the persistent Web Backend.
-   **Kubernetes API**: The Web Backend communicates with the K8s API to spawn and monitor Indexer Jobs.

### Architecture Diagram

```mermaid
graph TD
    User[User Browser] -->|HTTP/Ingress| Web[Web Backend (Django)]
    
    subgraph Kubernetes Cluster
        Web -->|Reads| PVC[(Shared Index Storage)]
        Web -->|Spawns| Job[Indexer Job]
        Job -->|Writes| PVC
        
        Web -.->|K8s API| K8s[Kubernetes Control Plane]
    end
    
    Job -->|Clones| GitHub[GitHub Repositories]
```

---

## 2. Semantic Code Search Indexer (CLI)

The core indexing logic is handled by the `semantic-code-search-indexer` utility. While typically managed by the Web App, it can be run manually for debugging.

### Command Structure
Run via `npm` from the indexer directory:

```bash
npm run index -- <TARGET_PATH> [OPTIONS]
```

### Arguments
| Argument | Description | Example |
| :--- | :--- | :--- |
| `<TARGET_PATH>` | **Required**. Relative or absolute path to the codebase to index. | `../dbt-mcp` |
| `--clean` | Clears any existing index for this target before starting. Recommended for full rebuilds. | `--clean` |
| `--concurrency <N>` | Number of parallel processing threads. Adjust based on CPU availability. | `--concurrency 16` |

### Example
```bash
# Index the dbt-mcp repo with 16 threads, cleaning old data first
npm run index -- ../dbt-mcp --clean --concurrency 16
```

---

## 3. Installation & Setup

### Prerequisites
-   **Docker Desktop** with Kubernetes enabled.
-   **kubectl** configured to point to `docker-desktop`.
-   **Python 3.9+** (for local backend development).

### Step 1: Build Container Images
Build the Docker images for both the web application and the indexer.

```bash
# Build Web Backend
cd /path/to/CodePathfinder
docker build -t codepathfinder:local .

# Build Indexer (assuming source is available)
cd /path/to/semantic-code-search-indexer
docker build -t indexer:local .
```

### Step 2: Apply Kubernetes Manifests
Deploy the namespace, storage, RBAC, and web application.

```bash
cd /path/to/CodePathfinder
kubectl apply -f k8s-manifests.yaml
```

### Step 3: Network Configuration
Add the ingress host to your local hosts file to access the app via the browser.

**Mac/Linux (`/etc/hosts`):**
```text
127.0.0.1 code-pathfinder.local
```

### Step 4: Access the Application
Open your browser to [http://code-pathfinder.local](http://code-pathfinder.local).

---

## 4. Troubleshooting

### Common Issues

#### 1. "Connection Refused" when accessing the Web App
-   **Cause**: Ingress controller might not be running or mapped to localhost ports.
-   **Fix**: Ensure Docker Desktop has "Enable Kubernetes" checked. Verify NGINX ingress is installed or use `kubectl port-forward` as a fallback:
    ```bash
    kubectl port-forward svc/codepathfinder-web -n code-pathfinder 8080:80
    ```
    Then access via `http://localhost:8080`.

#### 2. Indexing Job Stuck in "Pending"
-   **Cause**: Insufficient resources (CPU/Memory) in Docker Desktop.
-   **Fix**: Increase Docker Desktop resource limits (Settings -> Resources). Check pod status:
    ```bash
    kubectl describe pod -l job-name=<job-name> -n code-pathfinder
    ```

#### 3. Web App Cannot Read Index
-   **Cause**: Permissions issue on the Shared PVC or path mismatch.
-   **Fix**: Verify the `INDEX_DATA_PATH` in the ConfigMap matches the mount path in both the Deployment and Job templates.

### Log Locations

| Component | Access Command | Description |
| :--- | :--- | :--- |
| **Web Backend** | `kubectl logs -l app=codepathfinder-web -n code-pathfinder` | Django application logs, request errors, and job spawning logs. |
| **Indexer Jobs** | `kubectl logs -l job-name=<job_name> -n code-pathfinder` | Output from the indexing process, including progress and parsing errors. |
| **K8s Events** | `kubectl get events -n code-pathfinder` | Cluster-level events (pod scheduling, image pull errors, etc.). |

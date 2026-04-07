import logging
import os
import re
from kubernetes import client, config
import docker
import time
from django.conf import settings
from elasticsearch import Elasticsearch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FRAGILE CONTRACT: these strings are matched against indexer log output.
# If the upstream Elastic semantic code indexer changes its log phrasing,
# stage detection will break silently. Update both here and file a Phase 2
# ticket to add structured cpf_event JSON lines to the indexer instead.
# Source: indexer/src/commands/index_command.ts, git_helper.ts,
#         full_index_producer.ts, indexer_worker.ts
# ---------------------------------------------------------------------------
_LOG_STAGE_PATTERNS = {
    'initializing': 'Starting index command',
    'cloning_clone': 'Cloning ',                        # "Cloning <url> to <path>..."
    'cloning_pull': 'Pulling latest changes',           # "Repository already exists at ... Pulling latest changes..."
    'enqueuing': 'Found ',                              # "Found N files to process."
    'processing_watch': 'Watching queue for ',          # watch mode
    'processing': 'Running worker for ',                # normal processing
    # Mid-run markers: appear in every log tail during active processing
    'processing_dequeue': 'Dequeued batch of',          # worker actively consuming queue
    'processing_commit': 'Successfully indexed and committed batch',
    'finalizing': '--- Finished processing for:',       # "--- Finished processing for: <repo> ---"
    'finalizing_all': 'All repositories processed.',
    'watching': 'Queue empty, entering polling mode',   # already used by existing code
}

_LOG_ERROR_PATTERNS = [
    # (substring_to_match, stage, user_message)
    ('Failed to clone', 'error', 'Failed to clone repository. Check the URL and GitHub token.'),
    ('Repository not found at', 'error', 'Repository path not found. Try resetting and re-running.'),
    ('JavaScript heap out of memory', 'error', 'Indexer ran out of memory. Try reducing concurrency.'),
    ('out of memory', 'error', 'Indexer ran out of memory. Try reducing concurrency.'),
    ('SIGTERM', 'stopped', 'Job was terminated (manual stop or OOM kill).'),
    ('Received SIGKILL', 'stopped', 'Job was killed.'),
    ('ECONNREFUSED', 'stalled', 'Network error connecting to Elasticsearch. Check connectivity.'),
    ('ETIMEDOUT', 'stalled', 'Connection to Elasticsearch timed out.'),
    ('socket hang up', 'stalled', 'Network error connecting to Elasticsearch.'),
    ('rate limit', 'error', 'GitHub rate limit or auth error — check your token.'),
    ('HTTP 403', 'error', 'GitHub auth error (HTTP 403) — check your token.'),
    ('HTTP 401', 'error', 'GitHub auth error (HTTP 401) — check your token.'),
]

# Chunks-per-file heuristic: 1 indexed file ≈ 3 ES documents (chunks).
# Used only when total_files is known. Capped at 85% to leave room for
# finalizing/watching stages. Replace with exact ratio in Phase 2.
_CHUNKS_PER_FILE = 3
_STALL_THRESHOLD_MINUTES = 15


def _parse_stage_from_logs(log_text: str, project, es_doc_count: int = 0) -> dict:
    """
    Derive the current indexing stage and progress from pod log text + ES doc count.

    Returns a dict of PathfinderProject field updates (may be empty if nothing changed).
    Caller is responsible for saving with update_fields.

    Monotonicity rule: progress_pct only increases within a run; never goes backwards.
    Error patterns take priority over normal stage progression.
    """
    from django.utils import timezone

    updates = {}
    now = timezone.now()

    # --- 1. Check error/stop patterns first (highest priority) ---------------
    for pattern, stage, message in _LOG_ERROR_PATTERNS:
        if pattern.lower() in log_text.lower():
            updates['current_stage'] = stage
            updates['stage_message'] = message
            # Don't update progress_pct on error — preserve last good value
            return updates

    # --- 2. Determine stage from progression markers -------------------------
    new_stage = project.current_stage  # default: no change

    if _LOG_STAGE_PATTERNS['watching'] in log_text:
        new_stage = 'watching' if project.watch_mode else 'finalizing'
    elif _LOG_STAGE_PATTERNS['finalizing'] in log_text or _LOG_STAGE_PATTERNS['finalizing_all'] in log_text:
        new_stage = 'finalizing'
    elif (
        _LOG_STAGE_PATTERNS['processing_watch'] in log_text
        or _LOG_STAGE_PATTERNS['processing'] in log_text
        or _LOG_STAGE_PATTERNS['processing_dequeue'] in log_text
        or _LOG_STAGE_PATTERNS['processing_commit'] in log_text
    ):
        new_stage = 'processing'
    elif _LOG_STAGE_PATTERNS['enqueuing'] in log_text:
        # Parse total_files from "Found N files to process."
        match = re.search(r'Found (\d+) files to process', log_text)
        if match:
            found = int(match.group(1))
            if found != project.total_files:
                updates['total_files'] = found
        new_stage = 'enqueuing'
    elif _LOG_STAGE_PATTERNS['cloning_clone'] in log_text or _LOG_STAGE_PATTERNS['cloning_pull'] in log_text:
        new_stage = 'cloning'
    elif _LOG_STAGE_PATTERNS['initializing'] in log_text:
        new_stage = 'initializing'

    if new_stage:
        updates['current_stage'] = new_stage

    # --- 3. Calculate progress_pct -------------------------------------------
    stage = updates.get('current_stage', project.current_stage)
    total = updates.get('total_files', project.total_files)

    stage_base_pct = {
        'initializing': 2,
        'cloning': 10,
        'enqueuing': 20,
        'processing': 20,  # will be refined below
        'finalizing': 90,
        'watching': 100,
    }

    if stage == 'processing' and total > 0 and es_doc_count > 0:
        raw_pct = round(es_doc_count / max(total * _CHUNKS_PER_FILE, 1) * 65 + 20)
        new_pct = min(85, raw_pct)
    elif stage in stage_base_pct:
        new_pct = stage_base_pct[stage]
    else:
        new_pct = project.progress_pct  # no change for error/stalled/stopped

    # Monotonic enforcement: never go backwards
    updates['progress_pct'] = max(project.progress_pct, new_pct)

    # --- 4. ES doc count tracking + stall detection --------------------------
    if es_doc_count > project.files_processed:
        updates['files_processed'] = es_doc_count
        updates['last_progress_at'] = now
    elif (
        stage == 'processing'
        and project.last_progress_at
        and (now - project.last_progress_at).total_seconds() > _STALL_THRESHOLD_MINUTES * 60
    ):
        # timezone-aware comparison — both are UTC
        updates['current_stage'] = 'stalled'
        updates['stage_message'] = f'No new documents indexed in {_STALL_THRESHOLD_MINUTES} minutes — indexer may be stalled.'

    # Clear stage_message on clean stage transitions
    if 'current_stage' in updates and updates['current_stage'] not in ('error', 'stalled', 'stopped'):
        updates.setdefault('stage_message', '')

    return updates


def reset_project_progress(project):
    """
    Clear all progress tracking fields when a job is started or reset.
    Call this before triggering a new indexer run.
    """
    from projects.models import PathfinderProject
    PathfinderProject.objects.filter(pk=project.pk).update(
        current_stage='',
        progress_pct=0,
        total_files=0,
        files_processed=0,
        stage_message='',
        last_progress_at=None,
    )


def get_elasticsearch_config():
    """
    Get Elasticsearch configuration from SystemSettings (database only).

    Returns:
        dict with endpoint, api_key, cloud_id, user, password, index, inference_id
    """
    from core.models import SystemSettings
    db_settings = SystemSettings.get_settings()

    return {
        'endpoint': db_settings.elasticsearch_endpoint or None,
        'cloud_id': db_settings.elasticsearch_cloud_id or None,
        'api_key': db_settings.elasticsearch_api_key or None,
        'user': db_settings.elasticsearch_user or None,
        'password': db_settings.elasticsearch_password or None,
        'index': db_settings.elasticsearch_index or 'code-chunks',
        'inference_id': db_settings.elasticsearch_inference_id or '.elser-2-elasticsearch',
    }


def validate_elasticsearch_config():
    """
    Validate that Elasticsearch is properly configured before starting indexing jobs.
    
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
        If is_valid is False, error_message contains a user-friendly error description.
    """
    es_config = get_elasticsearch_config()
    errors = []
    
    # Check for connection method (endpoint or cloud_id)
    if not es_config['endpoint'] and not es_config['cloud_id']:
        errors.append("Elasticsearch endpoint or Cloud ID is not configured")
    
    # Check for authentication (api_key or user/password)
    has_api_key = bool(es_config['api_key'] and es_config['api_key'].strip())
    has_user_pass = bool(es_config['user'] and es_config['user'].strip() and 
                        es_config['password'] and es_config['password'].strip())
    
    if not has_api_key and not has_user_pass:
        errors.append("Elasticsearch authentication is not configured (missing API key or username/password)")
    
    if errors:
        error_msg = "Elasticsearch configuration is incomplete. " + ". ".join(errors) + "."
        error_msg += " Please configure Elasticsearch settings in Settings → System before running indexing jobs."
        return False, error_msg
    
    return True, None


def get_es_client():
    """
    Get configured Elasticsearch client.

    Returns:
        Elasticsearch client or None if credentials are missing
    """
    config = get_elasticsearch_config()

    # Need either endpoint or cloud_id
    if not config['endpoint'] and not config['cloud_id']:
        logger.error("Elasticsearch credentials missing: no endpoint or cloud_id")
        return None

    # Need either api_key or user/password
    if not config['api_key'] and not (config['user'] and config['password']):
        logger.error("Elasticsearch credentials missing: no api_key or user/password")
        return None

    try:
        if config['cloud_id']:
            # Cloud connection
            if config['api_key']:
                return Elasticsearch(cloud_id=config['cloud_id'], api_key=config['api_key'])
            else:
                return Elasticsearch(
                    cloud_id=config['cloud_id'],
                    basic_auth=(config['user'], config['password'])
                )
        else:
            # Direct endpoint connection
            if config['api_key']:
                return Elasticsearch(config['endpoint'], api_key=config['api_key'])
            else:
                return Elasticsearch(
                    config['endpoint'],
                    basic_auth=(config['user'], config['password'])
                )
    except Exception as e:
        logger.error(f"Failed to create Elasticsearch client: {e}")
        return None


def delete_elasticsearch_index(project):
    """
    Deletes the Elasticsearch index associated with a project.

    Args:
        project: PathfinderProject instance

    Returns:
        tuple: (success: bool, message: str)
    """
    index_name = project.custom_index_name

    if not index_name:
        logger.warning(f"Project {project.id} has no custom_index_name, skipping ES index deletion")
        return True, "No index to delete"

    try:
        es_client = get_es_client()
        if not es_client:
            return False, "Could not connect to Elasticsearch"

        # Check if index exists
        if es_client.indices.exists(index=index_name):
            es_client.indices.delete(index=index_name)
            logger.info(f"Deleted Elasticsearch index: {index_name}")
            return True, f"Index '{index_name}' deleted successfully"
        else:
            logger.info(f"Elasticsearch index '{index_name}' does not exist, nothing to delete")
            return True, f"Index '{index_name}' did not exist"

    except Exception as e:
        logger.error(f"Failed to delete Elasticsearch index '{index_name}': {e}")
        return False, str(e)

def _build_indexer_args(project):
    """
    Builds the argument list for the indexer command based on project configuration.
    Format: [repo_url] [--option value] [--flag]
    """
    args = []
    
    # Repository URL with optional custom index name
    if project.custom_index_name:
        args.append(f"{project.repository_url}:{project.custom_index_name}")
    else:
        args.append(project.repository_url)
    
    # Add token if provided (fallback to user's global token)
    token = project.github_token
    if not token:
        try:
            # Check if user has connected GitHub account
            if hasattr(project.user, 'github_settings') and project.user.github_settings.github_token:
                token = project.user.github_settings.github_token
        except Exception:
            # Ignore errors if github_settings doesn't exist
            pass
            
    if token:
        args.extend(["--token", token])
    
    # Add branch if specified
    if project.branch:
        args.extend(["--branch", project.branch])
    
    # Add flags
    if project.clean_index:
        args.append("--clean")
    
    if project.pull_before_index:
        args.append("--pull")
    
    if project.watch_mode:
        args.append("--watch")
    
    # Add concurrency (always include, has default value)
    args.extend(["--concurrency", str(project.concurrency)])
    
    return args

def trigger_local_indexer_job(project):
    """
    Triggers a local Docker container to run the semantic indexer.
    Fallback when Kubernetes is not available.
    """
    try:
        # Validate Elasticsearch configuration before starting
        is_valid, error_msg = validate_elasticsearch_config()
        if not is_valid:
            logger.error(f"Elasticsearch validation failed: {error_msg}")
            return False, error_msg
        
        docker_client = docker.from_env()

        # Get Elasticsearch config from database/environment
        es_config = get_elasticsearch_config()

        # Define environment variables (same as K8s)
        # Local Elasticsearch configuration
        # Since we're on the same Docker network, use the service name directly
        es_endpoint = es_config['endpoint'] or "http://elasticsearch:9200"
        # Convert localhost/127.0.0.1 to service name for Docker network access
        if 'localhost' in es_endpoint or '127.0.0.1' in es_endpoint:
            es_endpoint = es_endpoint.replace('localhost', 'elasticsearch').replace('127.0.0.1', 'elasticsearch')
        # Also handle host.docker.internal (fallback for external ES)
        if 'host.docker.internal' in es_endpoint and 'elasticsearch' not in es_endpoint:
            # Keep host.docker.internal if it's explicitly set for external ES
            pass

        environment = {
            "ELASTICSEARCH_ENDPOINT": es_endpoint,
            "ELASTICSEARCH_API_KEY": es_config['api_key'] or "",
            "ELASTICSEARCH_USER": es_config['user'] or "",
            "ELASTICSEARCH_PASSWORD": es_config['password'] or "",
            "ELASTICSEARCH_INFERENCE_ID": es_config['inference_id'],
            "ELASTICSEARCH_INDEX": es_config['index'],
            "SEMANTIC_CODE_INDEXER_LANGUAGES": "typescript,javascript,markdown,yaml,java,go,python,json,gradle,properties,text,handlebars,c,cpp,sql",
            "BATCH_SIZE": "1",  # Reduced to 1 for local development to avoid resource issues
            "OTEL_LOGGING_ENABLED": "false",
            "OTEL_SERVICE_NAME": "semantic-code-search-indexer",
            "NODE_ENV": "production",
        }

        # Add cloud_id if using Elastic Cloud
        if es_config['cloud_id']:
            environment["ELASTICSEARCH_CLOUD_ID"] = es_config['cloud_id']
        
        # Run the container
        # We use the image built by docker-compose
        image_name = "pathfinder-prototype-indexer:latest"
        
        # Dynamically detect the Docker network by finding the network of the web container
        # This ensures we use the correct network name regardless of docker-compose project name
        network_name = None
        try:
            # Try to find the web container and get its network
            web_containers = docker_client.containers.list(filters={"name": "pathfinder-prototype-web"})
            if web_containers:
                web_container = web_containers[0]
                web_networks = web_container.attrs.get('NetworkSettings', {}).get('Networks', {})
                if web_networks:
                    network_name = list(web_networks.keys())[0]
                    logger.info(f"Detected network: {network_name}")
        except Exception as e:
            logger.warning(f"Could not auto-detect network: {e}")
        
        # Fallback to common network names if auto-detection fails
        if not network_name:
            # Try common network name patterns
            for fallback_network in ["pathfinder-prototype_default", "pathfinder_default"]:
                try:
                    docker_client.networks.get(fallback_network)
                    network_name = fallback_network
                    logger.info(f"Using fallback network: {network_name}")
                    break
                except:
                    continue
        
        if not network_name:
            raise Exception("Could not find Docker network. Ensure docker-compose services are running.")
        
        container = docker_client.containers.run(
            image_name,
            command=["index"] + _build_indexer_args(project),
            environment=environment,
            detach=True,
            remove=False, # Keep for logs/status check
            labels={"app": "indexer-cli", "project-id": str(project.id)},
            name=f"indexer-job-{project.id}-{int(time.time())}",
            network_mode=network_name  # Connect to same network as web/db
        )
        
        logger.info(f"Local Docker container started: {container.name}")
        return True, f"Local job {container.name} started successfully."

    except Exception as e:
        logger.error(f"Failed to start local Docker job: {e}")
        return False, str(e)

def trigger_indexer_job(project):
    """
    Triggers a Kubernetes Job to run the semantic indexer for the given project.
    """
    try:
        # Validate Elasticsearch configuration before starting
        is_valid, error_msg = validate_elasticsearch_config()
        if not is_valid:
            logger.error(f"Elasticsearch validation failed: {error_msg}")
            return False, error_msg
        
        # Load kube config. 
        # Tries in-cluster first, falls back to local ~/.kube/config
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except Exception:
                # Fallback to local Docker if K8s config fails
                logger.warning("Kubernetes config not found. Falling back to local Docker execution.")
                return trigger_local_indexer_job(project)

        batch_v1 = client.BatchV1Api()

        # Define the Job
        # Note: These values should ideally come from settings or a ConfigMap
        namespace = "codepathfinder"
        image_name = "us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/indexer:latest"
        
        # Delete any existing jobs for this project to avoid conflicts
        try:
            jobs = batch_v1.list_namespaced_job(
                namespace=namespace,
                label_selector=f"project-id={project.id}"
            )
            for job in jobs.items:
                batch_v1.delete_namespaced_job(
                    name=job.metadata.name,
                    namespace=namespace,
                    propagation_policy='Background'
                )
        except Exception as e:
            # Log but don't fail if deletion fails
            print(f"Warning: Could not delete existing jobs: {str(e)}")
        
        # Construct the Job object with unique timestamp
        import time
        job_name = f"indexer-job-{project.id}-{int(time.time())}"
        
        # Define the container
        container = client.V1Container(
            name="indexer",
            image=image_name,
            image_pull_policy="Always",
            command=["node", "dist/index.js", "index"],
            args=_build_indexer_args(project),
            # Local Elasticsearch configuration
            env=[
                client.V1EnvVar(
                    name="ELASTICSEARCH_ENDPOINT",
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name="codepathfinder-secrets",
                            key="ELASTICSEARCH_ENDPOINT"
                        )
                    )
                ),
                client.V1EnvVar(
                    name="ELASTICSEARCH_API_KEY",
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name="codepathfinder-secrets",
                            key="ELASTICSEARCH_API_KEY"
                        )
                    )
                ),
                client.V1EnvVar(name="ELASTICSEARCH_INFERENCE_ID", value=".elser-2-elasticsearch"),
                client.V1EnvVar(name="ELASTICSEARCH_INDEX", value="code-chunks"),
                client.V1EnvVar(name="SEMANTIC_CODE_INDEXER_LANGUAGES", value="typescript,javascript,markdown,yaml,java,go,python,json,gradle,properties,text,handlebars,c,cpp,sql"),
                client.V1EnvVar(name="BATCH_SIZE", value="10"),  # EIS rate limit is 6k docs/min; 10 is safe and ~10x faster than 1
                client.V1EnvVar(name="OTEL_LOGGING_ENABLED", value="true"),
                client.V1EnvVar(name="OTEL_SERVICE_NAME", value="semantic-code-search-indexer"),
                client.V1EnvVar(name="OTEL_EXPORTER_OTLP_ENDPOINT", value="http://otel-collector-service.codepathfinder.svc.cluster.local:4318"),
                client.V1EnvVar(name="NODE_ENV", value="production"),
            ],
            volume_mounts=[
                client.V1VolumeMount(
                    name="index-data",
                    mount_path="/app/index-data"
                )
            ],
            resources=client.V1ResourceRequirements(
                limits={"cpu": "2", "memory": "2Gi"},
                requests={"cpu": "250m", "memory": "256Mi"}
            )
        )

        # Define the volume — emptyDir gives each job its own scratch space (queue.db is
        # throwaway per-run state; incremental-update state lives in the ES _settings index).
        # This replaces the RWO PVC that serialized all jobs to run one at a time.
        volume = client.V1Volume(
            name="index-data",
            empty_dir=client.V1EmptyDirVolumeSource()
        )

        # Define the template
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": "indexer-cli", "project-id": str(project.id)}),
            spec=client.V1PodSpec(
                restart_policy="Never",
                service_account_name="indexer-sa",
                containers=[container],
                volumes=[volume],
                image_pull_secrets=[client.V1LocalObjectReference(name="artifact-registry-key")]
            )
        )

        # Define the Job spec
        spec = client.V1JobSpec(
            ttl_seconds_after_finished=86400, # 24 hours
            backoff_limit=4,
            active_deadline_seconds=86400,  # 24 hours - increased for large repos like ClickHouse
            template=template
        )

        # Instantiate the Job object — labels on the Job metadata (not just the pod template)
        # are required so list_namespaced_job(label_selector=...) can find this job for
        # status polling and cleanup.
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=namespace,
                labels={"app": "indexer-cli", "project-id": str(project.id)}
            ),
            spec=spec
        )

        # Create the Job
        api_response = batch_v1.create_namespaced_job(
            body=job,
            namespace=namespace
        )
        logger.info(f"Job created. status='{api_response.status}'")
        return True, f"Job {job_name} created successfully."

    except Exception as e:
        logger.error(f"Failed to create Job: {e}")
        return False, str(e)

def stop_indexer_job(project):
    """
    Stops (deletes) the Kubernetes Job for the given project.
    """
    try:
        # Load kube config
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except Exception:
                 # Fallback to local Docker
                docker_client = docker.from_env()
                containers = docker_client.containers.list(filters={"label": [f"app=indexer-cli", f"project-id={project.id}"]})
                if not containers:
                    return False, "No running local job found."
                
                for container in containers:
                    container.stop()
                    container.remove()
                return True, "Local indexing job stopped."

        batch_v1 = client.BatchV1Api()
        namespace = "codepathfinder"

        # Job name format must match creation
        # Since we append timestamp, we need to find the job by label selector
        label_selector = f"app=indexer-cli,project-id={project.id}"
        
        jobs = batch_v1.list_namespaced_job(namespace=namespace, label_selector=label_selector)
        
        if not jobs.items:
            return False, "No running job found for this project."

        # Delete all matching jobs (should usually be one active)
        for job in jobs.items:
            batch_v1.delete_namespaced_job(
                name=job.metadata.name,
                namespace=namespace,
                body=client.V1DeleteOptions(propagation_policy='Foreground')
            )
            logger.info(f"Job {job.metadata.name} deleted.")
            
        return True, "Indexing job stopped successfully."

    except Exception as e:
        logger.error(f"Failed to stop Job: {e}")
        return False, str(e)


def check_and_update_project_status(project):
    """
    Checks the status of the Kubernetes Job for the project and updates the project status.
    """
    from django.utils import timezone
    from projects.models import PathfinderProject

    # If indexer is in watch mode, it will handle its own status

    # Grace period: If project was updated < 10s ago and is running, skip check
    # This avoids race conditions where the job is created but not yet listed
    if project.status == 'running':
        import datetime

        # Ensure updated_at is aware or naive consistent with timezone.now()
        now = timezone.now()
        if project.updated_at:
             # Calculate diff safely
            diff = now - project.updated_at
            if diff.total_seconds() < 10:
                logger.debug(f"Skipping status check for {project.name} (startup grace period)")
                return

            # Timeout check: If running for more than 2 hours with no job found, mark as failed
            # This prevents projects from being stuck indefinitely
            STUCK_TIMEOUT_HOURS = 2
            if diff.total_seconds() > (STUCK_TIMEOUT_HOURS * 3600):
                logger.warning(f"Project {project.name} has been 'running' for over {STUCK_TIMEOUT_HOURS} hours. Will check for orphaned state.")

    try:
        # Load kube config
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except Exception:
                # Fallback to local Docker
                docker_client = docker.from_env()
                # Check all containers (including stopped ones to see exit code)
                containers = docker_client.containers.list(all=True, filters={"label": [f"app=indexer-cli", f"project-id={project.id}"]})
                
                if not containers:
                    if project.status == 'running':
                        # Check if we've exceeded the stuck timeout
                        now = timezone.now()
                        if project.updated_at:
                            diff = now - project.updated_at
                            STUCK_TIMEOUT_HOURS = 2
                            if diff.total_seconds() > (STUCK_TIMEOUT_HOURS * 3600):
                                # Project has been "running" for too long with no container - mark as failed
                                project.status = 'failed'
                                project.save()
                                logger.warning(f"Project {project.name} marked as failed: no container found after {STUCK_TIMEOUT_HOURS} hours")
                                return
                        # Otherwise just reset to pending (job might have been cleaned up)
                        project.status = 'pending'
                        project.save()
                    return

                # Sort by creation time
                # Docker SDK doesn't give easy timestamp sort, but we can try
                # For now, just take the first one or iterate
                container = containers[0] # Simplification
                
                status_changed = False
                if container.status == 'running':
                    new_status = 'running'
                    # Check for idle/watching signal in logs even if running
                    try:
                        import datetime as dt
                        # Primary signal: silence. Watch/polling mode produces no logs.
                        # Get the last log line with its timestamp to detect queue-drained state.
                        last_log_bytes = container.logs(tail=1, timestamps=True)
                        if last_log_bytes:
                            last_line = last_log_bytes.decode('utf-8').strip()
                            # Docker timestamp format: "2026-03-24T13:56:48.513000000Z <message>"
                            # Nanosecond precision — truncate to microseconds for Python < 3.11
                            ts_str = last_line.split(' ')[0]
                            ts_str = re.sub(r'(\.\d{6})\d+Z?$', r'\1', ts_str.rstrip('Z')) + '+00:00'
                            try:
                                last_log_time = dt.datetime.fromisoformat(ts_str)
                                silence_secs = (timezone.now() - last_log_time).total_seconds()
                                if silence_secs > 120:  # 2+ minutes of silence = queue drained
                                    new_status = 'watching' if project.watch_mode else 'completed'
                                    if new_status == 'completed':
                                        logger.info(f"Project {project.name} is idle but running in local container {container.name}. Marking as completed.")
                            except ValueError:
                                pass  # Malformed timestamp — fall through to log-content check

                        # Fallback: scan log content for explicit watch-mode phrases
                        if new_status == 'running':
                            log_output = container.logs(tail=200).decode('utf-8')
                            if "Worker will continue running..." in log_output or "Watching queue for" in log_output:
                                new_status = 'watching' if project.watch_mode else 'completed'
                                if new_status == 'completed':
                                    logger.info(f"Project {project.name} is idle but running in local container {container.name}. Marking as completed.")

                        # Update stage and progress
                        if new_status in ('watching', 'completed'):
                            # Queue is drained — override stale progress with final values
                            PathfinderProject.objects.filter(pk=project.pk).update(
                                current_stage='watching' if new_status == 'watching' else '',
                                progress_pct=100,
                            )
                        else:
                            log_output = container.logs(tail=200).decode('utf-8')
                            es_doc_count = 0
                            try:
                                es_client = get_es_client()
                                if es_client and project.custom_index_name:
                                    res = es_client.count(index=project.custom_index_name)
                                    es_doc_count = res.get('count', 0)
                            except Exception:
                                pass
                            progress_updates = _parse_stage_from_logs(log_output, project, es_doc_count)
                            if progress_updates:
                                PathfinderProject.objects.filter(pk=project.pk).update(**progress_updates)
                    except Exception as e:
                        logger.debug(f"Could not parse stage from local container logs: {e}")

                    if project.status != new_status:
                        project.status = new_status
                        status_changed = True
                elif container.status == 'exited':
                    exit_code = container.attrs['State']['ExitCode']
                    if exit_code == 0:
                        if project.status != 'completed':
                            project.status = 'completed'
                            project.current_stage = ''
                            project.progress_pct = 100
                            status_changed = True
                    else:
                        if project.status != 'failed':
                            project.status = 'failed'
                            status_changed = True
                
                if status_changed:
                    project.save()
                return

        batch_v1 = client.BatchV1Api()
        namespace = "codepathfinder"
        label_selector = f"app=indexer-cli,project-id={project.id}"
        
        jobs = batch_v1.list_namespaced_job(namespace=namespace, label_selector=label_selector)
        
        if not jobs.items:
            # If status is running or pending but no job found, it might have been deleted or finished
            if project.status in ['running', 'pending']:
                # Check Elasticsearch as fallback
                es_client = get_es_client()
                if es_client and project.custom_index_name:
                    try:
                        res = es_client.count(index=project.custom_index_name)
                        if res['count'] > 0:
                            project.status = 'completed'
                            project.current_stage = ''
                            project.progress_pct = 100
                        else:
                            # Still nothing, maybe it really failed or never started
                            project.status = 'pending'
                    except Exception:
                         # Index might not exist yet if it failed early
                         project.status = 'pending'
                else:
                    project.status = 'pending'
                project.save()
            return

        # Get the most recent job
        # Jobs are not guaranteed to be ordered, so sort by creation timestamp
        job = sorted(jobs.items, key=lambda j: j.metadata.creation_timestamp, reverse=True)[0]
        
        # IMPORTANT: Check for failed jobs FIRST, even if there are no active pods
        # This handles cases where the job timed out (activeDeadlineSeconds exceeded)
        # or all pods failed and were cleaned up
        if job.status.failed and job.status.failed > 0:
            if project.status != 'failed':
                project.status = 'failed'
                project.save()
                logger.info(f"Updated project {project.name} status to failed (K8s job failed)")
            return
        
        if job.status.succeeded and job.status.succeeded > 0:
            if project.status != 'completed' or project.progress_pct != 100:
                project.status = 'completed'
                project.current_stage = ''
                project.progress_pct = 100
                project.save()
                logger.info(f"Updated project {project.name} status to completed")
            return

        # Check for active pods (job still running)
        status_changed = False
        if job.status.active and job.status.active > 0:
            new_status = 'running'
            
            # Check for Watch Mode signal in logs
            try:
                core_v1 = client.CoreV1Api()
                pods = core_v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=f"app=indexer-cli,project-id={project.id}"
                )
                if pods.items:
                    # Get most recent pod
                    pod = sorted(pods.items, key=lambda p: p.metadata.creation_timestamp, reverse=True)[0]
                    
                    if pod.status.phase == 'Running':
                        import datetime as dt
                        # Primary signal: silence. Watch/polling mode produces no logs.
                        # Get the last log line with timestamp to detect queue-drained state.
                        last_log_line = core_v1.read_namespaced_pod_log(
                            name=pod.metadata.name,
                            namespace=namespace,
                            tail_lines=1,
                            timestamps=True,
                        )
                        if last_log_line:
                            ts_str = last_log_line.split(' ')[0]
                            # Nanosecond precision — truncate to microseconds for Python < 3.11
                            ts_str = re.sub(r'(\.\d{6})\d+Z?$', r'\1', ts_str.rstrip('Z')) + '+00:00'
                            try:
                                from django.utils import timezone as tz
                                last_log_time = dt.datetime.fromisoformat(ts_str)
                                silence_secs = (tz.now() - last_log_time).total_seconds()
                                if silence_secs > 120:
                                    new_status = 'watching' if project.watch_mode else 'completed'
                                    if new_status == 'completed':
                                        logger.info(f"Project {project.name} is idle but running in pod {pod.metadata.name}. Marking as completed.")
                            except ValueError:
                                pass  # Malformed timestamp — fall through to log-content check

                        # Fallback: scan log content for explicit polling-mode phrase
                        logs = core_v1.read_namespaced_pod_log(
                            name=pod.metadata.name,
                            namespace=namespace,
                            tail_lines=200
                        )
                        if new_status == 'running' and "Queue empty, entering polling mode..." in logs:
                            if project.watch_mode:
                                new_status = 'watching'
                            else:
                                # Resource finished indexing but is hanging in polling mode
                                new_status = 'completed'
                                logger.info(f"Project {project.name} is idle but running in pod {pod.metadata.name}. Marking as completed.")

                        # Update stage and progress
                        if new_status in ('watching', 'completed'):
                            # Queue is drained — override stale progress with final values
                            PathfinderProject.objects.filter(pk=project.pk).update(
                                current_stage='watching' if new_status == 'watching' else '',
                                progress_pct=100,
                            )
                        else:
                            # If total_files is unknown, read the log head (first 8KB) to find
                            # "Found N files to process" — it appears early and scrolls out of tail.
                            if not project.total_files:
                                try:
                                    log_head = core_v1.read_namespaced_pod_log(
                                        name=pod.metadata.name,
                                        namespace=namespace,
                                        limit_bytes=8192,
                                    )
                                    logs = log_head + logs
                                except Exception:
                                    pass

                            es_doc_count = 0
                            try:
                                es_client = get_es_client()
                                if es_client and project.custom_index_name:
                                    res = es_client.count(index=project.custom_index_name)
                                    es_doc_count = res.get('count', 0)
                            except Exception:
                                pass
                            progress_updates = _parse_stage_from_logs(logs, project, es_doc_count)
                            if progress_updates:
                                PathfinderProject.objects.filter(pk=project.pk).update(**progress_updates)
            except Exception as e:
                logger.warning(f"Failed to check logs for watching status on project {project.id}: {e}")

            if project.status != new_status:
                project.status = new_status
                if new_status == 'completed':
                    project.current_stage = ''
                    project.progress_pct = 100
                status_changed = True
        
        if status_changed:
            project.save()
            logger.info(f"Updated project {project.name} status to {project.status}")

    except Exception as e:
        logger.error(f"Failed to check job status for project {project.name}: {e}")


def track_project_usage(project, user):
    """
    Track project usage atomically for both aggregate and per-user counters.

    Best-effort tracking: swallows exceptions to never fail requests.

    Args:
        project: PathfinderProject instance
        user: Django User instance

    Returns:
        None
    """
    if not user or not user.is_authenticated:
        return

    try:
        project.increment_usage(user)
    except Exception as e:
        logger.warning(f"Failed to track project usage: {e}", exc_info=True)

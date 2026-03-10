from django.db import models
from django.conf import settings
import secrets
import hashlib

class PathfinderProject(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('watching', 'Watching'),
        ('stopped', 'Stopped'),
    ]

    is_enabled = models.BooleanField(default=True, help_text="Manual toggle to enable/disable project search and access")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='projects')
    shared_with = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='shared_projects', blank=True, help_text="Users who can view this project")
    name = models.CharField(max_length=255)
    repository_url = models.URLField()
    
    # Optional indexer configuration fields
    github_token = models.CharField(max_length=255, blank=True, null=True, help_text="GitHub Personal Access Token for private repositories")
    branch = models.CharField(max_length=255, blank=True, null=True, help_text="Specific branch to index (default: auto-detect)")
    custom_index_name = models.CharField(max_length=255, blank=True, default='', help_text="Custom Elasticsearch index name (default: auto-generated as project-{id})")
    
    # Indexer options
    clean_index = models.BooleanField(default=False, help_text="Delete existing index before starting (full rebuild)")
    pull_before_index = models.BooleanField(default=False, help_text="Git pull before indexing (for incremental updates)")
    watch_mode = models.BooleanField(default=False, help_text="Keep indexer running for continuous updates")
    concurrency = models.IntegerField(default=4, help_text="Number of parallel workers (recommended: CPU core count)")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """
        Override save to auto-generate custom_index_name if not provided.
        Format: project-{id}
        """
        # For new objects without an ID yet, we need to save first to get the ID
        is_new = self.pk is None

        if is_new:
            # Save first to get the ID
            super().save(*args, **kwargs)
            # Now generate the index name if not provided
            if not self.custom_index_name:
                self.custom_index_name = f"project-{self.pk}"
                # Save again with the index name (using update to avoid recursion)
                PathfinderProject.objects.filter(pk=self.pk).update(custom_index_name=self.custom_index_name)
        else:
            # For existing objects, generate index name if missing
            if not self.custom_index_name:
                self.custom_index_name = f"project-{self.pk}"
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.status})"


class ProjectAPIKey(models.Model):
    """
    API keys for project-scoped access to MCP tools and chat.
    Keys are hashed using SHA256 and only shown once upon creation.
    """
    SCOPE_CHOICES = [
        ('mcp', 'MCP Tools Only'),
        ('chat', 'Chat Only'),
        ('otel', 'OTel Ingest Only'),
        ('all', 'All Access'),
    ]

    prefix = models.CharField(max_length=8, help_text="Key prefix for display (e.g., 'cpf_abc')")
    hashed_key = models.CharField(max_length=128, help_text="SHA256 hash of the full API key")
    label = models.CharField(max_length=50, default="CLI Key", help_text="User-friendly label (e.g., 'My Laptop')")
    project = models.ForeignKey(PathfinderProject, on_delete=models.CASCADE, related_name='api_keys')
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default='mcp', help_text="Access scope for this key")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, help_text="Last time this key was used")
    is_active = models.BooleanField(default=True, help_text="Inactive keys are rejected")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Project API Key"
        verbose_name_plural = "Project API Keys"

    def __str__(self):
        return f"{self.prefix}... ({self.label}) - {self.project.name}"

    @staticmethod
    def generate_key():
        """
        Generate a new API key and return (plain_key, hashed_key, prefix).

        Format: cpf_<prefix>_<random_string>
        Example: cpf_abc123_xyz789def456ghi789jkl012mno345pqr678stu901vwx234

        Returns:
            tuple: (plain_key, hashed_key, prefix)
        """
        # Generate prefix (8 random alphanumeric characters)
        prefix = secrets.token_urlsafe(6)[:8]

        # Generate random key (40 characters for strong security)
        random_part = secrets.token_urlsafe(30)[:40]

        # Combine: cpf_<prefix>_<random>
        plain_key = f"cpf_{prefix}_{random_part}"

        # Hash the full key
        hashed_key = ProjectAPIKey.hash_key(plain_key)

        return plain_key, hashed_key, prefix

    @staticmethod
    def hash_key(key):
        """
        Hash an API key using SHA256.

        Args:
            key (str): The plain text API key

        Returns:
            str: The SHA256 hash of the key
        """
        return hashlib.sha256(key.encode()).hexdigest()

    def validate_key(self, key):
        """
        Validate a plain text key against this record's hashed key.

        Args:
            key (str): The plain text API key to validate

        Returns:
            bool: True if the key matches and is active, False otherwise
        """
        if not self.is_active:
            return False

        return self.hashed_key == ProjectAPIKey.hash_key(key)


class JobRun(models.Model):
    """
    Tracks historical job runs for audit, debugging, and history queries.
    Each run represents a single indexing job execution.
    """
    project = models.ForeignKey(
        PathfinderProject,
        on_delete=models.CASCADE,
        related_name='job_runs',
        help_text="The project this job run belongs to"
    )
    job_id = models.CharField(
        max_length=100,
        help_text="Kubernetes job name or Docker container ID"
    )
    started_at = models.DateTimeField(
        help_text="When the job was started"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the job completed (null if still running)"
    )
    final_status = models.CharField(
        max_length=20,
        choices=PathfinderProject.STATUS_CHOICES,
        default='running',
        help_text="Final status of the job run"
    )
    options = models.JSONField(
        default=dict,
        help_text="Job options used (clean_index, branch, concurrency, etc.)"
    )
    result = models.JSONField(
        default=dict,
        help_text="Job results (files_indexed, documents_created, errors, etc.)"
    )
    error_message = models.TextField(
        blank=True,
        default='',
        help_text="Error message if job failed"
    )
    triggered_by = models.CharField(
        max_length=50,
        default='web',
        help_text="How the job was triggered (web, api, schedule)"
    )

    class Meta:
        ordering = ['-started_at']
        verbose_name = "Job Run"
        verbose_name_plural = "Job Runs"
        indexes = [
            models.Index(fields=['project', '-started_at']),
            models.Index(fields=['final_status']),
        ]

    def __str__(self):
        return f"{self.project.name} - {self.job_id} ({self.final_status})"

    @property
    def duration_seconds(self):
        """Calculate job duration in seconds."""
        if self.completed_at and self.started_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None

    @property
    def is_running(self):
        """Check if the job is still running."""
        return self.final_status in ['running', 'watching']


class OtelCollectionSettings(models.Model):
    """
    Per-project OpenTelemetry collection configuration.
    Allows project owners to send OTLP traces/metrics/logs
    to CodePathfinder's integrated Elasticsearch.
    """
    project = models.OneToOneField(
        PathfinderProject,
        on_delete=models.CASCADE,
        related_name='otel_settings',
        help_text="The project this OTel configuration belongs to"
    )
    enabled = models.BooleanField(default=False)
    collect_traces = models.BooleanField(default=True)
    collect_metrics = models.BooleanField(default=True)
    collect_logs = models.BooleanField(default=True)
    service_name = models.CharField(
        max_length=255, blank=True,
        help_text="service.name for telemetry (auto-generated from project name if blank)"
    )
    traces_index = models.CharField(max_length=255, blank=True)
    metrics_index = models.CharField(max_length=255, blank=True)
    logs_index = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "OTel Collection Settings"
        verbose_name_plural = "OTel Collection Settings"

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"OTel for {self.project.name} ({status})"

    def save(self, *args, **kwargs):
        # OTel indices always use the project PK so the collector can route
        # deterministically via the cpf.project.id resource attribute.
        otel_slug = f"project-{self.project.pk}"
        if not self.traces_index:
            self.traces_index = f"traces-customer.{otel_slug}"
        if not self.metrics_index:
            self.metrics_index = f"metrics-customer.{otel_slug}"
        if not self.logs_index:
            self.logs_index = f"logs-customer.{otel_slug}"
        if not self.service_name:
            self.service_name = self.project.name.lower().replace(' ', '-')
        super().save(*args, **kwargs)

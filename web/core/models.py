from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models


class User(AbstractUser):
    """
    Custom User model for CodePathfinder.
    Standard users are active by default and do not require Admin approval.
    """
    favorite_chat_project = models.ForeignKey(
        'projects.PathfinderProject',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='favorited_by_users',
        help_text="Default project for chat interface"
    )
    setup_wizard_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the admin completed (or dismissed) the setup wizard"
    )


class SystemSettings(models.Model):
    """Singleton model for global admin configuration."""

    # Elasticsearch Configuration
    elasticsearch_endpoint = models.CharField(
        max_length=255,
        blank=True,
        help_text="Self-hosted Elasticsearch URL (e.g., http://elasticsearch:9200)"
    )
    elasticsearch_cloud_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Elastic Cloud ID (alternative to endpoint)"
    )
    elasticsearch_user = models.CharField(max_length=255, blank=True)
    elasticsearch_password = models.CharField(max_length=255, blank=True)
    elasticsearch_api_key = models.CharField(max_length=255, blank=True)
    elasticsearch_index = models.CharField(
        max_length=255,
        default='code-chunks',
        help_text="Default index name for code chunks"
    )
    elasticsearch_inference_id = models.CharField(
        max_length=255,
        default='.elser-2-elasticsearch',
        help_text="Inference endpoint for semantic search"
    )
    indexer_concurrency = models.IntegerField(
        default=8,
        help_text="Default number of parallel indexing workers (8 recommended for ELSER)"
    )

    # OTel Collector Configuration
    otel_collector_enabled = models.BooleanField(
        default=False,
        help_text="Enable OTel collection globally (master switch)"
    )
    otel_collector_endpoint = models.CharField(
        max_length=500, blank=True,
        help_text="OTLP gRPC collector endpoint (e.g., https://otel.codepathfinder.com:4317)"
    )
    otel_collector_http_endpoint = models.CharField(
        max_length=500, blank=True,
        help_text="OTLP HTTP collector endpoint (e.g., https://otel.codepathfinder.com:4318)"
    )

    # Skills GitHub Repository
    skills_repo_url = models.URLField(
        blank=True,
        help_text="GitHub repo containing skills (e.g., https://github.com/org/skills)"
    )
    skills_repo_token = models.CharField(
        max_length=255,
        blank=True,
        help_text="Personal Access Token for private repos"
    )
    skills_repo_branch = models.CharField(
        max_length=255,
        default='main',
        help_text="Branch to sync skills from"
    )

    # Metadata
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='system_settings_updates'
    )

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # Enforce singleton
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # Prevent deletion of singleton

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "System Settings"


class UserGitHubSettings(models.Model):
    """User's GitHub authentication for write operations."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='github_settings'
    )
    github_username = models.CharField(max_length=255, blank=True)
    github_token = models.CharField(
        max_length=255,
        blank=True,
        help_text="Personal Access Token for GitHub API operations"
    )
    skills_repo_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Personal GitHub repo containing user's own skills (e.g., https://github.com/user/my-skills)"
    )
    skills_repo_branch = models.CharField(
        max_length=100,
        default='main',
        help_text="Branch to sync personal skills from"
    )
    last_validated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time the token was validated against GitHub API"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User GitHub Settings"
        verbose_name_plural = "User GitHub Settings"

    def __str__(self):
        return f"GitHub settings for {self.user.username}"

    @property
    def has_token(self):
        """Check if user has a GitHub token configured."""
        return bool(self.github_token)


# LLMProvider and LLMModel classes have been removed.
# LLM configuration is now managed through LibreChat settings.
# To drop the database tables, run the migration created for this change.

from django.conf import settings
from django.db import models


class Skill(models.Model):
    """
    AI agent skill with instructions and metadata.

    Skills can be synced from a GitHub repository or created locally.
    They are indexed in Elasticsearch for semantic search.
    """

    # Core skill definition
    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique skill identifier (e.g., 'code-review', 'test-generator')"
    )
    description = models.TextField(
        help_text="Brief description of what the skill does (used for semantic search)"
    )
    instructions = models.TextField(
        help_text="Full instructions/prompt for the AI agent"
    )

    # Skill configuration
    allowed_tools = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tool names the skill is allowed to use"
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Tags for categorization and filtering"
    )
    context_files = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dict of file paths to content for additional context"
    )

    # Curation and usage
    is_curated = models.BooleanField(
        default=False,
        help_text="Whether this skill is curated/verified by administrators"
    )
    usage_count = models.IntegerField(
        default=0,
        help_text="Number of times this skill has been used"
    )

    # Scope: global skills visible to all, personal skills visible only to creator
    SCOPE_GLOBAL = 'global'
    SCOPE_PERSONAL = 'personal'
    SCOPE_CHOICES = [
        (SCOPE_GLOBAL, 'Global'),
        (SCOPE_PERSONAL, 'Personal'),
    ]
    scope = models.CharField(
        max_length=20,
        choices=SCOPE_CHOICES,
        default=SCOPE_GLOBAL,
        db_index=True,
        help_text="Global skills are visible to all users; Personal skills are only visible to their creator"
    )
    source_repo_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="For personal skills: the user's skills repo URL they were synced from"
    )

    # GitHub sync metadata
    github_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Path in the skills repository (e.g., 'skills/code-review/SKILL.md')"
    )
    last_synced = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this skill was synced from GitHub"
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this skill is available for use"
    )
    is_hidden = models.BooleanField(
        default=False,
        help_text="Whether this skill is hidden from UI/API (exists in GitHub but not visible)"
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this skill was soft-deleted (hidden by admin). Set to re-enable restoration."
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_skills',
        help_text="User who deleted (hid) this skill"
    )

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_skills',
        help_text="User who created this skill (null if synced from GitHub)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Skill"
        verbose_name_plural = "Skills"
        ordering = ['-is_curated', '-usage_count', 'name']

    def __str__(self):
        return self.name

    def increment_usage(self):
        """Increment usage count atomically."""
        Skill.objects.filter(pk=self.pk).update(usage_count=models.F('usage_count') + 1)

    def to_dict(self):
        """Convert skill to dictionary for API/MCP responses."""
        return {
            'name': self.name,
            'description': self.description,
            'instructions': self.instructions,
            'allowed_tools': self.allowed_tools,
            'tags': self.tags,
            'is_curated': self.is_curated,
            'scope': self.scope,
        }


class SkillUsage(models.Model):
    """
    Track per-user skill usage for personalized recommendations.

    This model enables:
    - Showing user's most-used skills in the Chat skill selector
    - Tracking skill popularity per user
    - Falling back to global popularity for new users
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='skill_usages',
        help_text="User who used the skill"
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name='user_usages',
        help_text="Skill that was used"
    )
    used_at = models.DateTimeField(
        auto_now=True,
        help_text="Last time this skill was used by this user"
    )
    usage_count = models.IntegerField(
        default=1,
        help_text="Number of times this user has used this skill"
    )

    class Meta:
        verbose_name = "Skill Usage"
        verbose_name_plural = "Skill Usages"
        unique_together = ['user', 'skill']
        ordering = ['-used_at']
        indexes = [
            models.Index(fields=['user', '-used_at']),
            models.Index(fields=['user', '-usage_count']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.skill.name} ({self.usage_count}x)"

    def increment(self):
        """Increment usage count and update timestamp."""
        from django.db.models import F
        SkillUsage.objects.filter(pk=self.pk).update(
            usage_count=F('usage_count') + 1
        )
        self.refresh_from_db()

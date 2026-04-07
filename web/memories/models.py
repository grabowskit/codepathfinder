from django.conf import settings
from django.db import models


class Memory(models.Model):
    """
    A stored piece of knowledge for AI chat recall.

    Two types:
    - text: short fact or convention (e.g. "We use pytest-django for all tests")
    - document: longer markdown doc imported for semantic retrieval

    Two scopes:
    - user: personal, visible only to the creator
    - organization: admin-managed, visible to all users
    """

    TYPE_TEXT = 'text'
    TYPE_DOCUMENT = 'document'
    TYPE_CHOICES = [
        (TYPE_TEXT, 'Text Statement'),
        (TYPE_DOCUMENT, 'Document'),
    ]

    SCOPE_USER = 'user'
    SCOPE_ORGANIZATION = 'organization'
    SCOPE_CHOICES = [
        (SCOPE_USER, 'User'),
        (SCOPE_ORGANIZATION, 'Organization'),
    ]

    title = models.CharField(
        max_length=255,
        help_text="Short title for this memory"
    )
    content = models.TextField(
        help_text="Memory content (markdown or plain text)"
    )
    memory_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_TEXT,
        db_index=True,
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Tags for categorization and auto-injection trigger matching"
    )
    scope = models.CharField(
        max_length=20,
        choices=SCOPE_CHOICES,
        default=SCOPE_USER,
        db_index=True,
        help_text="User memories are private; Organization memories are shared (admin-managed)"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_memories',
    )

    # Status
    is_active = models.BooleanField(default=True)
    is_hidden = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_memories',
    )

    usage_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Memory"
        verbose_name_plural = "Memories"
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['title', 'scope', 'created_by'],
                name='unique_memory_title_scope_user',
            )
        ]

    def __str__(self):
        return self.title

    def increment_usage(self, user=None):
        """
        Increment usage count atomically for both aggregate and per-user tracking.

        Args:
            user: Django User instance (optional for backward compatibility)
        """
        from django.db.models import F

        # Increment aggregate counter
        Memory.objects.filter(pk=self.pk).update(usage_count=F('usage_count') + 1)

        # Increment per-user counter if user provided
        if user and user.is_authenticated:
            usage, created = MemoryUsage.objects.get_or_create(
                user=user,
                memory=self,
                defaults={'usage_count': 1}
            )
            if not created:
                MemoryUsage.objects.filter(pk=usage.pk).update(usage_count=F('usage_count') + 1)

    def to_dict(self):
        return {
            'id': self.pk,
            'title': self.title,
            'content': self.content,
            'memory_type': self.memory_type,
            'tags': self.tags,
            'scope': self.scope,
            'created_by': self.created_by_id,
            'usage_count': self.usage_count,
        }


class MemoryUsage(models.Model):
    """Track per-user memory usage for analytics."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memory_usages',
    )
    memory = models.ForeignKey(
        Memory,
        on_delete=models.CASCADE,
        related_name='user_usages',
    )
    used_at = models.DateTimeField(auto_now=True)
    usage_count = models.IntegerField(default=1)

    class Meta:
        verbose_name = "Memory Usage"
        verbose_name_plural = "Memory Usages"
        unique_together = ['user', 'memory']
        ordering = ['-used_at']
        indexes = [
            models.Index(fields=['user', '-used_at']),
            models.Index(fields=['user', '-usage_count']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.memory.title} ({self.usage_count}x)"

    def increment(self):
        from django.db.models import F
        MemoryUsage.objects.filter(pk=self.pk).update(usage_count=F('usage_count') + 1)
        self.refresh_from_db()

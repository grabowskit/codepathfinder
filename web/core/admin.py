from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, SystemSettings, UserGitHubSettings


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom User admin."""
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('username', 'email', 'first_name', 'last_name')


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    """Admin for global system settings (singleton)."""

    fieldsets = (
        ('Elasticsearch Configuration', {
            'fields': (
                'elasticsearch_endpoint',
                'elasticsearch_cloud_id',
                'elasticsearch_user',
                'elasticsearch_password',
                'elasticsearch_api_key',
                'elasticsearch_index',
                'elasticsearch_inference_id',
                'indexer_concurrency',
            ),
            'description': 'Configure connection to Elasticsearch for code search.'
        }),
        ('Skills Repository', {
            'fields': (
                'skills_repo_url',
                'skills_repo_token',
                'skills_repo_branch',
            ),
            'description': 'GitHub repository containing Skills (SKILL.md files).'
        }),
        ('OTel Collector', {
            'fields': (
                'otel_collector_enabled',
                'otel_collector_endpoint',
                'otel_collector_http_endpoint',
            ),
            'description': 'Global OpenTelemetry collector configuration for customer telemetry.'
        }),
        ('Metadata', {
            'fields': ('updated_at', 'updated_by'),
            'classes': ('collapse',),
        }),
    )

    readonly_fields = ('updated_at', 'updated_by')

    def has_add_permission(self, request):
        # Only allow one instance (singleton)
        return not SystemSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(UserGitHubSettings)
class UserGitHubSettingsAdmin(admin.ModelAdmin):
    """Admin for user GitHub settings."""
    list_display = ('user', 'github_username', 'has_token', 'last_validated_at', 'updated_at')
    list_filter = ('last_validated_at',)
    search_fields = ('user__username', 'github_username')
    readonly_fields = ('created_at', 'updated_at', 'last_validated_at')

    def has_token(self, obj):
        return obj.has_token
    has_token.boolean = True
    has_token.short_description = 'Token Set'


# LLMProvider and LLMModel admin classes have been removed.
# LLM configuration is now managed through LibreChat settings.

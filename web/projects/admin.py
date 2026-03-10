from django.contrib import admin
from .models import PathfinderProject, ProjectAPIKey, OtelCollectionSettings


@admin.register(PathfinderProject)
class PathfinderProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'status', 'repository_url', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'repository_url', 'user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    filter_horizontal = ('shared_with',)


@admin.register(ProjectAPIKey)
class ProjectAPIKeyAdmin(admin.ModelAdmin):
    list_display = ('prefix', 'label', 'project', 'is_active', 'created_at', 'last_used_at')
    list_filter = ('is_active', 'created_at', 'last_used_at')
    search_fields = ('prefix', 'label', 'project__name')
    readonly_fields = ('prefix', 'hashed_key', 'created_at', 'last_used_at')

    fieldsets = (
        ('Key Information', {
            'fields': ('prefix', 'hashed_key', 'label', 'is_active')
        }),
        ('Project', {
            'fields': ('project',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_used_at'),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        # API keys should be created via the API, not the admin
        return False


@admin.register(OtelCollectionSettings)
class OtelCollectionSettingsAdmin(admin.ModelAdmin):
    list_display = ('project', 'enabled', 'collect_traces', 'collect_metrics', 'collect_logs', 'updated_at')
    list_filter = ('enabled', 'collect_traces', 'collect_metrics', 'collect_logs')
    search_fields = ('project__name', 'service_name')
    readonly_fields = ('traces_index', 'metrics_index', 'logs_index', 'created_at', 'updated_at')

    fieldsets = (
        ('Project', {'fields': ('project',)}),
        ('Collection Settings', {
            'fields': ('enabled', 'collect_traces', 'collect_metrics', 'collect_logs', 'service_name')
        }),
        ('Generated Index Names (read-only)', {
            'fields': ('traces_index', 'metrics_index', 'logs_index'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

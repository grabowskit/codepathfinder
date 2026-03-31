from django.contrib import admin
from .models import Memory, MemoryUsage


@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
    list_display = ['title', 'scope', 'memory_type', 'created_by', 'usage_count', 'is_active', 'created_at']
    list_filter = ['scope', 'memory_type', 'is_active', 'is_hidden']
    search_fields = ['title', 'content']
    readonly_fields = ['created_at', 'updated_at', 'usage_count']


@admin.register(MemoryUsage)
class MemoryUsageAdmin(admin.ModelAdmin):
    list_display = ['user', 'memory', 'usage_count', 'used_at']
    list_filter = ['user']
    readonly_fields = ['used_at']

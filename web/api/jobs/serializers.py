"""
Serializers for the Jobs API.

Provides validation and formatting for:
- Project CRUD operations
- Job start/stop options
- Status responses with progress
- Job history
- Search requests
"""

from rest_framework import serializers
from projects.models import PathfinderProject


class JobOptionsSerializer(serializers.Serializer):
    """
    Serializer for job start options.

    These options control how the indexing job runs.
    """
    clean_index = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Delete existing index before starting (full rebuild). Default: false'
    )
    pull_before_index = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Git pull before indexing (for incremental updates). Default: false'
    )
    watch_mode = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Keep indexer running for continuous updates. Default: false'
    )
    branch = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=255,
        help_text='Specific branch to index. Default: auto-detect main/master'
    )
    concurrency = serializers.IntegerField(
        required=False,
        default=4,
        min_value=1,
        max_value=16,
        help_text='Number of parallel indexing workers (1-16). Default: 4'
    )


class ProjectCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new project.
    """
    auto_start = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
        help_text='Start indexing immediately after creation. Default: false'
    )
    options = JobOptionsSerializer(
        required=False,
        write_only=True,
        help_text='Options to use if auto_start is true'
    )

    class Meta:
        model = PathfinderProject
        fields = [
            'id', 'name', 'repository_url', 'branch', 'github_token',
            'clean_index', 'pull_before_index', 'watch_mode', 'concurrency',
            'auto_start', 'options'
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'name': {
                'required': True,
                'help_text': 'Display name for the project'
            },
            'repository_url': {
                'required': True,
                'help_text': 'Git repository URL (https://github.com/org/repo)'
            },
            'branch': {
                'required': False,
                'help_text': 'Branch to index. Default: auto-detect'
            },
            'github_token': {
                'required': False,
                'write_only': True,
                'help_text': 'GitHub personal access token (required for private repos)'
            },
            'concurrency': {
                'required': False,
                'help_text': 'Number of parallel workers (1-16). Default: 4'
            },
        }

    def validate_repository_url(self, value):
        """Validate repository URL format."""
        if not value:
            raise serializers.ValidationError('Repository URL is required')

        # Basic URL validation
        if not value.startswith(('https://', 'git@')):
            raise serializers.ValidationError(
                'Repository URL must start with https:// or git@'
            )

        return value

    def validate_concurrency(self, value):
        """Validate concurrency is within bounds."""
        if value is not None and (value < 1 or value > 16):
            raise serializers.ValidationError(
                'Concurrency must be between 1 and 16'
            )
        return value


class ProjectUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating project settings.
    """

    class Meta:
        model = PathfinderProject
        fields = [
            'name', 'branch', 'github_token',
            'clean_index', 'pull_before_index', 'watch_mode', 'concurrency',
            'is_enabled'
        ]
        extra_kwargs = {
            'name': {'required': False},
            'branch': {'required': False},
            'github_token': {'write_only': True, 'required': False},
            'is_enabled': {'required': False},
        }


class ProjectDetailSerializer(serializers.ModelSerializer):
    """
    Full project details serializer.
    """
    owner = serializers.SerializerMethodField()
    index_name = serializers.CharField(source='custom_index_name', read_only=True)
    shared_with_count = serializers.SerializerMethodField()

    class Meta:
        model = PathfinderProject
        fields = [
            'id', 'name', 'repository_url', 'branch', 'status',
            'is_enabled', 'index_name', 'owner', 'shared_with_count',
            'clean_index', 'pull_before_index', 'watch_mode', 'concurrency',
            'created_at', 'updated_at'
        ]
        read_only_fields = fields

    def get_owner(self, obj):
        return {
            'id': obj.user.id,
            'username': obj.user.username,
            'email': obj.user.email
        }

    def get_shared_with_count(self, obj):
        return obj.shared_with.count()


class JobStatusSerializer(serializers.Serializer):
    """
    Serializer for job status response.
    """
    project_id = serializers.IntegerField()
    project_name = serializers.CharField()
    repository_url = serializers.CharField()
    status = serializers.CharField()
    is_enabled = serializers.BooleanField()
    index_name = serializers.CharField()

    job = serializers.DictField(required=False, allow_null=True)
    progress = serializers.DictField(required=False, allow_null=True)
    elasticsearch = serializers.DictField(required=False, allow_null=True)
    options = serializers.DictField(required=False)
    logs = serializers.ListField(required=False, child=serializers.DictField())


class JobListItemSerializer(serializers.ModelSerializer):
    """
    Serializer for project list items.
    """
    links = serializers.SerializerMethodField()

    class Meta:
        model = PathfinderProject
        fields = [
            'id', 'name', 'repository_url', 'status', 'is_enabled',
            'created_at', 'updated_at', 'links'
        ]

    def get_links(self, obj):
        base_url = f'/api/v1/jobs/{obj.id}'
        links = {
            'status': f'{base_url}/status/',
        }

        if obj.status in ['running', 'watching']:
            links['stop'] = f'{base_url}/stop/'
            links['logs'] = f'{base_url}/logs/'
        else:
            links['start'] = f'{base_url}/start/'

        if obj.status == 'completed':
            links['search'] = f'{base_url}/search/'

        return links


class JobStartSerializer(serializers.Serializer):
    """
    Serializer for job start request.
    """
    clean_index = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Delete existing index before starting (full rebuild)'
    )
    pull_before_index = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Git pull before indexing'
    )
    watch_mode = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Keep indexer running for continuous updates'
    )
    branch = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=255,
        help_text='Branch to index'
    )
    concurrency = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=16,
        help_text='Number of parallel workers (1-16)'
    )

    def validate_concurrency(self, value):
        if value is not None and (value < 1 or value > 16):
            raise serializers.ValidationError(
                'Concurrency must be between 1 and 16'
            )
        return value


class JobRunSerializer(serializers.Serializer):
    """
    Serializer for job run history.
    """
    run_id = serializers.IntegerField(source='id')
    job_id = serializers.CharField()
    started_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField(allow_null=True)
    duration_seconds = serializers.SerializerMethodField()
    final_status = serializers.CharField()
    options = serializers.DictField()
    result = serializers.DictField()

    def get_duration_seconds(self, obj):
        if obj.completed_at and obj.started_at:
            return int((obj.completed_at - obj.started_at).total_seconds())
        return None


class JobSearchSerializer(serializers.Serializer):
    """
    Serializer for search requests.
    """
    query = serializers.CharField(
        required=True,
        min_length=1,
        max_length=1000,
        help_text='Search query text'
    )
    size = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=50,
        help_text='Maximum number of results (1-50)'
    )
    search_type = serializers.ChoiceField(
        required=False,
        default='semantic',
        choices=['semantic', 'keyword', 'symbol'],
        help_text='Search type: semantic (natural language), keyword (exact match), symbol (function/class names)'
    )


class CrossProjectSearchSerializer(JobSearchSerializer):
    """
    Serializer for cross-project search requests.
    """
    project_ids = serializers.ListField(
        required=False,
        child=serializers.IntegerField(),
        allow_empty=True,
        help_text='List of project IDs to search. If empty, searches all accessible projects.'
    )


class BulkStartSerializer(serializers.Serializer):
    """
    Serializer for bulk start requests.
    """
    project_ids = serializers.ListField(
        required=True,
        child=serializers.IntegerField(),
        min_length=1,
        max_length=10,
        help_text='List of project IDs to start (max 10)'
    )
    options = JobOptionsSerializer(
        required=False,
        help_text='Options to apply to all jobs'
    )


class BulkStopSerializer(serializers.Serializer):
    """
    Serializer for bulk stop requests.
    """
    project_ids = serializers.ListField(
        required=True,
        child=serializers.IntegerField(),
        min_length=1,
        max_length=10,
        help_text='List of project IDs to stop (max 10)'
    )


class LogEntrySerializer(serializers.Serializer):
    """
    Serializer for log entries.
    """
    timestamp = serializers.DateTimeField()
    level = serializers.CharField()
    message = serializers.CharField()


class JobLogsSerializer(serializers.Serializer):
    """
    Serializer for logs response.
    """
    project_id = serializers.IntegerField()
    project_name = serializers.CharField()
    job_id = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    logs = LogEntrySerializer(many=True)
    truncated = serializers.BooleanField()

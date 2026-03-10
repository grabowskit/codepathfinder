from rest_framework import serializers
from .models import ProjectAPIKey, PathfinderProject


class ProjectAPIKeySerializer(serializers.ModelSerializer):
    """
    Serializer for ProjectAPIKey model.

    For list/retrieve operations, only shows safe fields (no hashed_key).
    For create operations, returns the plain API key once.
    """
    # Read-only field to return the plain key on creation
    key = serializers.CharField(read_only=True, help_text="Full API key (shown only once)")
    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = ProjectAPIKey
        fields = ['id', 'prefix', 'label', 'project', 'project_name', 'key', 'created_at', 'last_used_at', 'is_active']
        read_only_fields = ['id', 'prefix', 'key', 'created_at', 'last_used_at', 'project_name', 'project']

    def create(self, validated_data):
        """
        Create a new API key and include the plain key in the response.
        """
        # Generate the API key
        plain_key, hashed_key, prefix = ProjectAPIKey.generate_key()

        # Create the key record
        api_key = ProjectAPIKey.objects.create(
            prefix=prefix,
            hashed_key=hashed_key,
            label=validated_data.get('label', 'CLI Key'),
            project=validated_data['project']
        )

        # Attach the plain key for one-time display
        api_key.key = plain_key

        return api_key


class ProjectAPIKeyListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing API keys (no sensitive data).
    """
    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = ProjectAPIKey
        fields = ['id', 'prefix', 'label', 'project', 'project_name', 'created_at', 'last_used_at', 'is_active']
        read_only_fields = fields

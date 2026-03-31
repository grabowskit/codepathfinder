"""
Data migration to populate default Elasticsearch settings for local development.
"""
from django.db import migrations


def populate_default_settings(apps, schema_editor):
    """Populate SystemSettings with local development defaults."""
    SystemSettings = apps.get_model('core', 'SystemSettings')

    # Get or create the singleton settings instance
    settings, created = SystemSettings.objects.get_or_create(pk=1)

    # Only populate if fields are empty (don't overwrite existing config)
    if not settings.elasticsearch_endpoint:
        settings.elasticsearch_endpoint = 'http://localhost:9200'
    if not settings.elasticsearch_user:
        settings.elasticsearch_user = 'elastic'
    if not settings.elasticsearch_index or settings.elasticsearch_index == 'code-chunks':
        settings.elasticsearch_index = 'pathfinder-skills'
    if not settings.elasticsearch_inference_id or settings.elasticsearch_inference_id == '.elser-2-elasticsearch':
        settings.elasticsearch_inference_id = '.elser-2-elastic'

    # Skills repository defaults
    if not settings.skills_repo_url:
        settings.skills_repo_url = 'https://github.com/YOUR_USERNAME/codepathfinder-skills'
    # skills_repo_token intentionally left empty — set via Admin Settings
    if not settings.skills_repo_branch or settings.skills_repo_branch == 'main':
        settings.skills_repo_branch = 'main'

    settings.save()


def reverse_migration(apps, schema_editor):
    """Reverse migration - clear the default settings."""
    # We don't actually want to delete data on reverse, just pass
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_usergithubsettings'),
    ]

    operations = [
        migrations.RunPython(populate_default_settings, reverse_migration),
    ]

# Generated manually for Claude MCP Connector OAuth Application

from django.db import migrations


def create_claude_oauth_app(apps, schema_editor):
    """Create pre-configured OAuth Application for Claude Desktop."""
    Application = apps.get_model('oauth2_provider', 'Application')
    User = apps.get_model('core', 'User')
    
    # Get admin user (first superuser)
    admin = User.objects.filter(is_superuser=True).first()
    if not admin:
        # Fallback to first user
        admin = User.objects.first()
    
    if not admin:
        return  # No users yet, skip
    
    # Create or update the application
    app, created = Application.objects.update_or_create(
        name='Claude MCP Connector',
        defaults={
            'client_id': 'codepathfinder-claude-mcp',
            'client_type': 'confidential',
            'authorization_grant_type': 'authorization-code',
            'redirect_uris': 'https://claude.ai/api/mcp/auth_callback https://claude.com/api/mcp/auth_callback',
            'user': admin,
            'skip_authorization': True,
        }
    )


def reverse_migration(apps, schema_editor):
    """Remove the Claude OAuth Application."""
    Application = apps.get_model('oauth2_provider', 'Application')
    Application.objects.filter(name='Claude MCP Connector').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('mcp_server', '0002_mcpsession_mcpmessagequeue'),
    ]

    operations = [
        migrations.RunPython(create_claude_oauth_app, reverse_migration),
    ]

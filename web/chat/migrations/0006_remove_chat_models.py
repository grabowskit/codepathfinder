"""
Remove legacy chat models (ChatConversation, ChatMessage, Artifact).
Chat functionality is now provided by LibreChat.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0005_add_chart_config_to_artifact'),
    ]

    operations = [
        migrations.DeleteModel(name='Artifact'),
        migrations.DeleteModel(name='ChatMessage'),
        migrations.DeleteModel(name='ChatConversation'),
    ]

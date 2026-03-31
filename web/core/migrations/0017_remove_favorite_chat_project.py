"""
Remove favorite_chat_project field from User model.
The field was used for the legacy custom chat interface, which has been removed.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_otel_collector_settings'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='favorite_chat_project',
        ),
    ]

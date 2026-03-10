from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_add_indexer_concurrency'),
    ]

    operations = [
        migrations.AddField(
            model_name='llmprovider',
            name='last_test_success',
            field=models.BooleanField(blank=True, help_text='Whether the most recent test succeeded', null=True),
        ),
        migrations.AddField(
            model_name='llmprovider',
            name='last_tested_at',
            field=models.DateTimeField(blank=True, help_text='When the provider was last tested', null=True),
        ),
        migrations.AddField(
            model_name='llmprovider',
            name='successful_requests',
            field=models.PositiveIntegerField(default=0, help_text='Number of successful requests using this provider'),
        ),
    ]

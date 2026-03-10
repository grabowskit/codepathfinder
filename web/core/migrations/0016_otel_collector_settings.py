from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_add_user_skills_repo_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='otel_collector_enabled',
            field=models.BooleanField(default=False, help_text='Enable OTel collection globally (master switch)'),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='otel_collector_endpoint',
            field=models.CharField(blank=True, help_text='OTLP gRPC collector endpoint (e.g., https://otel.codepathfinder.com:4317)', max_length=500),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='otel_collector_http_endpoint',
            field=models.CharField(blank=True, help_text='OTLP HTTP collector endpoint (e.g., https://otel.codepathfinder.com:4318)', max_length=500),
        ),
    ]

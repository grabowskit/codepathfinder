from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0009_add_job_run_model'),
    ]

    operations = [
        migrations.CreateModel(
            name='OtelCollectionSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=False)),
                ('collect_traces', models.BooleanField(default=True)),
                ('collect_metrics', models.BooleanField(default=True)),
                ('collect_logs', models.BooleanField(default=True)),
                ('service_name', models.CharField(blank=True, help_text='service.name for telemetry (auto-generated from project name if blank)', max_length=255)),
                ('traces_index', models.CharField(blank=True, max_length=255)),
                ('metrics_index', models.CharField(blank=True, max_length=255)),
                ('logs_index', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('project', models.OneToOneField(
                    help_text='The project this OTel configuration belongs to',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='otel_settings',
                    to='projects.pathfinderproject',
                )),
            ],
            options={
                'verbose_name': 'OTel Collection Settings',
                'verbose_name_plural': 'OTel Collection Settings',
            },
        ),
    ]

# Generated manually for indexing progress tracking feature
# Adds 6 new fields to PathfinderProject for stage, percent, file counts, and stall detection.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0010_otelcollectionsettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='pathfinderproject',
            name='current_stage',
            field=models.CharField(
                blank=True, default='',
                help_text='Current indexing stage (initializing/cloning/enqueuing/processing/finalizing/watching/stalled/error/stopped)',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='pathfinderproject',
            name='progress_pct',
            field=models.IntegerField(
                default=0,
                help_text='Estimated percent complete (0-100); monotonically increasing within a run',
            ),
        ),
        migrations.AddField(
            model_name='pathfinderproject',
            name='total_files',
            field=models.IntegerField(
                default=0,
                help_text="Total files to index, parsed from 'Found N files to process' log line",
            ),
        ),
        migrations.AddField(
            model_name='pathfinderproject',
            name='files_processed',
            field=models.IntegerField(
                default=0,
                help_text='Proxy: current ES document count divided by avg chunks/file',
            ),
        ),
        migrations.AddField(
            model_name='pathfinderproject',
            name='stage_message',
            field=models.TextField(
                blank=True, default='',
                help_text='Human-readable stage context or error reason shown to users',
            ),
        ),
        migrations.AddField(
            model_name='pathfinderproject',
            name='last_progress_at',
            field=models.DateTimeField(
                null=True, blank=True,
                help_text='Last time ES doc count increased; used for stall detection',
            ),
        ),
    ]

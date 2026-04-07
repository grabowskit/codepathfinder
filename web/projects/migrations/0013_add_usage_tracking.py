# Generated manually for usage tracking feature
# Adds usage_count field to PathfinderProject and creates ProjectUsage model for per-user tracking.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('projects', '0012_indexing_progress'),
    ]

    operations = [
        migrations.AddField(
            model_name='pathfinderproject',
            name='usage_count',
            field=models.IntegerField(
                default=0,
                help_text='Total times this project was used across all users',
            ),
        ),
        migrations.CreateModel(
            name='ProjectUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('used_at', models.DateTimeField(auto_now=True, help_text='Last time this user accessed this project')),
                ('usage_count', models.IntegerField(default=1, help_text='Number of times this user has used this project')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_usages', to='projects.pathfinderproject')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='project_usages', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Project Usage',
                'verbose_name_plural': 'Project Usages',
                'ordering': ['-used_at'],
                'unique_together': {('user', 'project')},
            },
        ),
        migrations.AddIndex(
            model_name='projectusage',
            index=models.Index(fields=['user', '-used_at'], name='projects_pr_user_id_5a8f12_idx'),
        ),
        migrations.AddIndex(
            model_name='projectusage',
            index=models.Index(fields=['user', '-usage_count'], name='projects_pr_user_id_e72c3d_idx'),
        ),
    ]

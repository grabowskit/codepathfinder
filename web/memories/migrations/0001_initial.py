from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Memory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(help_text='Short title for this memory', max_length=255)),
                ('content', models.TextField(help_text='Memory content (markdown or plain text)')),
                ('memory_type', models.CharField(
                    choices=[('text', 'Text Statement'), ('document', 'Document')],
                    db_index=True,
                    default='text',
                    max_length=20,
                )),
                ('tags', models.JSONField(blank=True, default=list, help_text='Tags for categorization and auto-injection trigger matching')),
                ('scope', models.CharField(
                    choices=[('user', 'User'), ('organization', 'Organization')],
                    db_index=True,
                    default='user',
                    help_text='User memories are private; Organization memories are shared (admin-managed)',
                    max_length=20,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('is_hidden', models.BooleanField(default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('usage_count', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_memories',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('deleted_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='deleted_memories',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Memory',
                'verbose_name_plural': 'Memories',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='memory',
            constraint=models.UniqueConstraint(
                fields=['title', 'scope', 'created_by'],
                name='unique_memory_title_scope_user',
            ),
        ),
        migrations.CreateModel(
            name='MemoryUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('used_at', models.DateTimeField(auto_now=True)),
                ('usage_count', models.IntegerField(default=1)),
                ('memory', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='user_usages',
                    to='memories.memory',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='memory_usages',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Memory Usage',
                'verbose_name_plural': 'Memory Usages',
                'ordering': ['-used_at'],
                'unique_together': {('user', 'memory')},
            },
        ),
        migrations.AddIndex(
            model_name='memoryusage',
            index=models.Index(fields=['user', '-used_at'], name='memories_me_user_id_d8cdf9_idx'),
        ),
        migrations.AddIndex(
            model_name='memoryusage',
            index=models.Index(fields=['user', '-usage_count'], name='memories_me_user_id_ba9cf0_idx'),
        ),
    ]

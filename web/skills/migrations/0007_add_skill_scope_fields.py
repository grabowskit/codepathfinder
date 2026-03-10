from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('skills', '0006_new_sample_skills'),
    ]

    operations = [
        migrations.AddField(
            model_name='skill',
            name='scope',
            field=models.CharField(
                choices=[('global', 'Global'), ('personal', 'Personal')],
                db_index=True,
                default='global',
                help_text="Global skills are visible to all users; Personal skills are only visible to their creator",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='skill',
            name='source_repo_url',
            field=models.CharField(
                blank=True,
                help_text="For personal skills: the user's skills repo URL they were synced from",
                max_length=500,
                null=True,
            ),
        ),
    ]

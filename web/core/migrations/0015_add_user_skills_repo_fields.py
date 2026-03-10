from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_remove_llm_provider_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='usergithubsettings',
            name='skills_repo_url',
            field=models.CharField(
                blank=True,
                help_text="Personal GitHub repo containing user's own skills (e.g., https://github.com/user/my-skills)",
                max_length=500,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='usergithubsettings',
            name='skills_repo_branch',
            field=models.CharField(
                default='main',
                help_text="Branch to sync personal skills from",
                max_length=100,
            ),
        ),
    ]

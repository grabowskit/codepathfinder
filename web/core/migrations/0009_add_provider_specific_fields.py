# Generated migration for provider-specific fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_set_providers_inactive'),
    ]

    operations = [
        # OpenAI-specific fields
        migrations.AddField(
            model_name='llmprovider',
            name='organization_id',
            field=models.CharField(blank=True, help_text='OpenAI Organization ID (optional)', max_length=100),
        ),
        migrations.AddField(
            model_name='llmprovider',
            name='project_id',
            field=models.CharField(blank=True, help_text='OpenAI Project ID (optional)', max_length=100),
        ),
        # Azure-specific fields
        migrations.AddField(
            model_name='llmprovider',
            name='azure_deployment_name',
            field=models.CharField(blank=True, help_text='Azure OpenAI deployment name', max_length=100),
        ),
        migrations.AddField(
            model_name='llmprovider',
            name='azure_api_version',
            field=models.CharField(blank=True, default='2024-02-01', help_text='Azure OpenAI API version', max_length=20),
        ),
        # AWS Bedrock-specific fields
        migrations.AddField(
            model_name='llmprovider',
            name='aws_region',
            field=models.CharField(blank=True, help_text='AWS region (e.g., us-east-1)', max_length=50),
        ),
        migrations.AddField(
            model_name='llmprovider',
            name='aws_access_key_id',
            field=models.CharField(blank=True, help_text='AWS Access Key ID (leave empty to use IAM role)', max_length=100),
        ),
        migrations.AddField(
            model_name='llmprovider',
            name='aws_secret_access_key',
            field=models.CharField(blank=True, help_text='AWS Secret Access Key', max_length=100),
        ),
        # Google Vertex AI-specific fields
        migrations.AddField(
            model_name='llmprovider',
            name='vertex_project',
            field=models.CharField(blank=True, help_text='Google Cloud project ID', max_length=100),
        ),
        migrations.AddField(
            model_name='llmprovider',
            name='vertex_location',
            field=models.CharField(blank=True, default='us-central1', help_text='Vertex AI location (e.g., us-central1)', max_length=50),
        ),
    ]

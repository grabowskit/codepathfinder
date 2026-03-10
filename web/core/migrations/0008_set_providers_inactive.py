# Generated migration to set all LLM providers to inactive by default

from django.db import migrations


def set_providers_inactive(apps, schema_editor):
    """
    Set all LLM providers to inactive.

    Admins must explicitly activate providers after configuring API keys.
    This prevents accidental usage of providers without proper configuration.
    """
    LLMProvider = apps.get_model('core', 'LLMProvider')
    LLMProvider.objects.all().update(is_active=False, is_default=False)


def reverse_set_providers_inactive(apps, schema_editor):
    """
    Reverse: Set Anthropic as active and default.
    """
    LLMProvider = apps.get_model('core', 'LLMProvider')
    anthropic = LLMProvider.objects.filter(provider='anthropic').first()
    if anthropic:
        anthropic.is_active = True
        anthropic.is_default = True
        anthropic.save()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_populate_llm_providers'),
    ]

    operations = [
        migrations.RunPython(set_providers_inactive, reverse_set_providers_inactive),
    ]

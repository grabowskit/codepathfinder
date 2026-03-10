from django.test import TestCase
from django.contrib.auth import get_user_model
from projects.models import PathfinderProject, OtelCollectionSettings, ProjectAPIKey

User = get_user_model()


class OtelCollectionSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.project = PathfinderProject.objects.create(
            user=self.user,
            name='Test Project',
            repository_url='https://github.com/test/repo',
        )

    def test_auto_generates_index_names(self):
        otel = OtelCollectionSettings.objects.create(project=self.project)
        self.assertTrue(otel.traces_index.startswith('traces-customer.'))
        self.assertTrue(otel.metrics_index.startswith('metrics-customer.'))
        self.assertTrue(otel.logs_index.startswith('logs-customer.'))

    def test_auto_generates_service_name(self):
        otel = OtelCollectionSettings.objects.create(project=self.project)
        self.assertEqual(otel.service_name, 'test-project')

    def test_custom_service_name_preserved(self):
        otel = OtelCollectionSettings.objects.create(
            project=self.project, service_name='my-custom-service'
        )
        self.assertEqual(otel.service_name, 'my-custom-service')

    def test_index_names_use_project_slug(self):
        self.project.refresh_from_db()
        otel = OtelCollectionSettings.objects.create(project=self.project)
        slug = self.project.custom_index_name
        self.assertEqual(otel.traces_index, f'traces-customer.{slug}')
        self.assertEqual(otel.metrics_index, f'metrics-customer.{slug}')
        self.assertEqual(otel.logs_index, f'logs-customer.{slug}')

    def test_enabled_default_false(self):
        otel = OtelCollectionSettings.objects.create(project=self.project)
        self.assertFalse(otel.enabled)

    def test_one_to_one_constraint(self):
        OtelCollectionSettings.objects.create(project=self.project)
        with self.assertRaises(Exception):
            OtelCollectionSettings.objects.create(project=self.project)

    def test_cascade_delete(self):
        OtelCollectionSettings.objects.create(project=self.project)
        self.project.delete()
        self.assertEqual(OtelCollectionSettings.objects.count(), 0)

    def test_str_representation(self):
        otel = OtelCollectionSettings.objects.create(project=self.project)
        self.assertIn('Test Project', str(otel))
        self.assertIn('disabled', str(otel))

    def test_str_enabled(self):
        otel = OtelCollectionSettings.objects.create(project=self.project, enabled=True)
        self.assertIn('enabled', str(otel))


class OtelScopeAPIKeyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.project = PathfinderProject.objects.create(
            user=self.user,
            name='Test',
            repository_url='https://github.com/t/r',
        )

    def test_otel_scope_key_creation(self):
        plain_key, hashed_key, prefix = ProjectAPIKey.generate_key()
        key = ProjectAPIKey.objects.create(
            project=self.project,
            prefix=prefix,
            hashed_key=hashed_key,
            label='OTel Key',
            scope='otel',
        )
        self.assertEqual(key.scope, 'otel')

    def test_otel_scope_in_choices(self):
        choices = dict(ProjectAPIKey.SCOPE_CHOICES)
        self.assertIn('otel', choices)
        self.assertEqual(choices['otel'], 'OTel Ingest Only')

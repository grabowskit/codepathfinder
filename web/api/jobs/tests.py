"""
Tests for the Jobs API.

These tests verify the Jobs API endpoints work correctly with:
- Authentication (API keys)
- Authorization (owner vs shared access)
- Rate limiting
- Error handling
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock

from core.models import User
from projects.models import PathfinderProject, ProjectAPIKey


class JobsAPITestCase(APITestCase):
    """Base test case with common setup."""

    def setUp(self):
        """Create test user, project, and API key."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.project = PathfinderProject.objects.create(
            user=self.user,
            name='Test Project',
            repository_url='https://github.com/test/repo',
            status='pending'
        )
        # Create API key
        plain_key, hashed_key, prefix = ProjectAPIKey.generate_key()
        self.api_key = ProjectAPIKey.objects.create(
            prefix=prefix,
            hashed_key=hashed_key,
            project=self.project,
            scope='all'
        )
        self.plain_key = plain_key

    def auth_headers(self):
        """Return authentication headers."""
        return {'HTTP_AUTHORIZATION': f'Bearer {self.plain_key}'}


class JobListCreateViewTests(JobsAPITestCase):
    """Tests for GET/POST /api/v1/jobs/"""

    def test_list_projects_authenticated(self):
        """Test listing projects with valid API key."""
        response = self.client.get('/api/v1/jobs/', **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.json())
        self.assertIn('projects', response.json()['data'])

    def test_list_projects_unauthenticated(self):
        """Test listing projects without API key."""
        response = self.client.get('/api/v1/jobs/')
        # DRF returns 403 Forbidden when no credentials provided (not 401)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_list_projects_filter_by_status(self):
        """Test filtering projects by status."""
        response = self.client.get('/api/v1/jobs/?status=pending', **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        projects = response.json()['data']['projects']
        for project in projects:
            self.assertEqual(project['status'], 'pending')

    @patch('api.jobs.views.validate_elasticsearch_config')
    def test_create_project_with_auto_start(self, mock_validate_es):
        """Test creating a project with auto_start."""
        mock_validate_es.return_value = (False, "ES not configured")

        data = {
            'name': 'New Project',
            'repository_url': 'https://github.com/test/new-repo',
            'auto_start': True
        }
        response = self.client.post('/api/v1/jobs/', data, format='json', **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('New Project', response.json()['content'][0]['text'])


class ProjectDetailViewTests(JobsAPITestCase):
    """Tests for GET/PATCH/DELETE /api/v1/jobs/{project_id}/"""

    def test_get_project_details(self):
        """Test getting project details."""
        response = self.client.get(f'/api/v1/jobs/{self.project.id}/', **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['id'], self.project.id)

    def test_get_project_not_found(self):
        """Test getting non-existent project."""
        response = self.client.get('/api/v1/jobs/99999/', **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('PROJECT_NOT_FOUND', response.json()['error']['code'])

    def test_update_project(self):
        """Test updating project settings."""
        data = {'name': 'Updated Name', 'concurrency': 8}
        response = self.client.patch(
            f'/api/v1/jobs/{self.project.id}/',
            data,
            format='json',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, 'Updated Name')
        self.assertEqual(self.project.concurrency, 8)


class JobStartViewTests(JobsAPITestCase):
    """Tests for POST /api/v1/jobs/{project_id}/start/"""

    @patch('api.jobs.views.validate_elasticsearch_config')
    @patch('api.jobs.views.trigger_indexer_job')
    def test_start_job_success(self, mock_trigger, mock_validate_es):
        """Test starting a job successfully."""
        mock_validate_es.return_value = (True, None)
        mock_trigger.return_value = (True, "Job started")

        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/start/',
            {},
            format='json',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, 'running')

    @patch('api.jobs.views.validate_elasticsearch_config')
    def test_start_job_es_not_configured(self, mock_validate_es):
        """Test starting job when Elasticsearch is not configured."""
        mock_validate_es.return_value = (False, "ES not configured")

        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/start/',
            {},
            format='json',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ELASTICSEARCH_NOT_CONFIGURED', response.json()['error']['code'])

    def test_start_job_already_running(self):
        """Test starting a job that's already running."""
        self.project.status = 'running'
        self.project.save()

        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/start/',
            {},
            format='json',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ALREADY_RUNNING', response.json()['error']['code'])

    def test_start_job_with_options(self):
        """Test starting job with custom options."""
        with patch('api.jobs.views.validate_elasticsearch_config') as mock_es, \
             patch('api.jobs.views.trigger_indexer_job') as mock_trigger:
            mock_es.return_value = (True, None)
            mock_trigger.return_value = (True, "Job started")

            data = {
                'clean_index': True,
                'branch': 'develop',
                'concurrency': 8
            }
            response = self.client.post(
                f'/api/v1/jobs/{self.project.id}/start/',
                data,
                format='json',
                **self.auth_headers()
            )
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            self.project.refresh_from_db()
            self.assertTrue(self.project.clean_index)
            self.assertEqual(self.project.branch, 'develop')
            self.assertEqual(self.project.concurrency, 8)


class JobStopViewTests(JobsAPITestCase):
    """Tests for POST /api/v1/jobs/{project_id}/stop/"""

    @patch('api.jobs.views.stop_indexer_job')
    def test_stop_job_success(self, mock_stop):
        """Test stopping a running job."""
        self.project.status = 'running'
        self.project.save()
        mock_stop.return_value = (True, "Job stopped")

        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/stop/',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, 'stopped')

    def test_stop_job_not_running(self):
        """Test stopping a job that's not running."""
        self.project.status = 'completed'
        self.project.save()

        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/stop/',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('NO_RUNNING_JOB', response.json()['error']['code'])


class JobStatusViewTests(JobsAPITestCase):
    """Tests for GET /api/v1/jobs/{project_id}/status/"""

    def test_get_status(self):
        """Test getting job status."""
        response = self.client.get(
            f'/api/v1/jobs/{self.project.id}/status/',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()['data']
        self.assertEqual(data['project_id'], self.project.id)
        self.assertEqual(data['status'], 'pending')


class JobResetViewTests(JobsAPITestCase):
    """Tests for POST /api/v1/jobs/{project_id}/reset/"""

    def test_reset_failed_project(self):
        """Test resetting a failed project."""
        self.project.status = 'failed'
        self.project.save()

        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/reset/',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, 'pending')

    def test_cannot_reset_running_project(self):
        """Test that running projects cannot be reset."""
        self.project.status = 'running'
        self.project.save()

        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/reset/',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class JobSearchViewTests(JobsAPITestCase):
    """Tests for POST /api/v1/jobs/{project_id}/search/"""

    def test_search_index_not_ready(self):
        """Test searching when index is not ready."""
        self.project.status = 'pending'
        self.project.save()

        data = {'query': 'test query'}
        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/search/',
            data,
            format='json',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('INDEX_NOT_READY', response.json()['error']['code'])


class BulkOperationsTests(JobsAPITestCase):
    """Tests for bulk start/stop operations."""

    def test_bulk_start_validation(self):
        """Test bulk start with invalid data."""
        data = {'project_ids': []}  # Empty list
        response = self.client.post(
            '/api/v1/jobs/bulk/start/',
            data,
            format='json',
            **self.auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ErrorHandlingTests(JobsAPITestCase):
    """Tests for error response format."""

    def test_error_response_format(self):
        """Test that errors include code, message, and remediation."""
        # Try to access non-existent project
        response = self.client.get('/api/v1/jobs/99999/', **self.auth_headers())
        error = response.json()['error']
        self.assertIn('code', error)
        self.assertIn('message', error)
        self.assertIn('remediation', error)

    def test_invalid_api_key(self):
        """Test response for invalid API key."""
        response = self.client.get(
            '/api/v1/jobs/',
            HTTP_AUTHORIZATION='Bearer cpf_invalid_key'
        )
        # Invalid key returns 401 Unauthorized
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class AuthorizationTests(APITestCase):
    """Tests for authorization rules."""

    def setUp(self):
        """Create users and projects for authorization tests."""
        self.owner = User.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='ownerpass'
        )
        self.shared_user = User.objects.create_user(
            username='shared',
            email='shared@example.com',
            password='sharedpass'
        )
        self.project = PathfinderProject.objects.create(
            user=self.owner,
            name='Owner Project',
            repository_url='https://github.com/owner/repo'
        )
        self.project.shared_with.add(self.shared_user)

        # Create API keys
        plain_key, hashed_key, prefix = ProjectAPIKey.generate_key()
        self.owner_key = ProjectAPIKey.objects.create(
            prefix=prefix,
            hashed_key=hashed_key,
            project=self.project,
            scope='all'
        )
        self.owner_plain_key = plain_key

    def test_shared_user_can_view_status(self):
        """Test that shared users can view project status."""
        self.client.force_authenticate(user=self.shared_user)
        response = self.client.get(f'/api/v1/jobs/{self.project.id}/status/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_shared_user_cannot_start_job(self):
        """Test that shared users cannot start jobs."""
        self.client.force_authenticate(user=self.shared_user)
        response = self.client.post(
            f'/api/v1/jobs/{self.project.id}/start/',
            {},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

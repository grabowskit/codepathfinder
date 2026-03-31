"""
Tests for Job Management MCP tools.

Tests cover:
1. job_manage tool with all actions (start, stop, reset, create, update, delete, bulk ops)
2. job_status tool with all actions (status, list, details, logs, history)
3. Helper functions (_resolve_project_for_job, _get_job_logs, _get_index_stats)

Run with:
    docker-compose exec web python manage.py test mcp_server.test_job_tools

Or with pytest:
    docker-compose exec web pytest mcp_server/test_job_tools.py -v
"""

from django.test import TestCase
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model

from projects.models import PathfinderProject, JobRun
from mcp_server.tools import (
    job_manage,
    job_status,
    _resolve_project_for_job,
    _get_job_logs,
    _get_index_stats,
    ToolError
)

User = get_user_model()


class TestResolveProjectForJob(TestCase):
    """Tests for _resolve_project_for_job helper function."""

    def setUp(self):
        """Create test user and project."""
        self.owner = User.objects.create_user(
            username='owner',
            email='owner@test.com',
            password='testpass'
        )
        self.shared_user = User.objects.create_user(
            username='shared',
            email='shared@test.com',
            password='testpass'
        )
        self.other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass'
        )
        self.project = PathfinderProject.objects.create(
            user=self.owner,
            name='test-project',
            repository_url='https://github.com/test/repo',
            status='pending'
        )
        self.project.shared_with.add(self.shared_user)

    def test_resolve_by_name(self):
        """Test resolving project by name."""
        result = _resolve_project_for_job(self.owner, project='test-project')
        self.assertEqual(result.id, self.project.id)

    def test_resolve_by_id(self):
        """Test resolving project by ID."""
        result = _resolve_project_for_job(self.owner, project_id=self.project.id)
        self.assertEqual(result.id, self.project.id)

    def test_resolve_case_insensitive(self):
        """Test that project name lookup is case-insensitive."""
        result = _resolve_project_for_job(self.owner, project='TEST-PROJECT')
        self.assertEqual(result.id, self.project.id)

    def test_shared_user_can_access(self):
        """Test that shared users can access the project."""
        result = _resolve_project_for_job(self.shared_user, project='test-project')
        self.assertEqual(result.id, self.project.id)

    def test_other_user_denied(self):
        """Test that non-authorized users are denied."""
        with self.assertRaises(ToolError) as context:
            _resolve_project_for_job(self.other_user, project='test-project')
        self.assertIn('Access denied', str(context.exception))

    def test_shared_user_write_access_denied(self):
        """Test that shared users cannot get write access."""
        with self.assertRaises(ToolError) as context:
            _resolve_project_for_job(
                self.shared_user,
                project='test-project',
                require_write_access=True
            )
        self.assertIn('Read-only access', str(context.exception))

    def test_owner_write_access_allowed(self):
        """Test that owner can get write access."""
        result = _resolve_project_for_job(
            self.owner,
            project='test-project',
            require_write_access=True
        )
        self.assertEqual(result.id, self.project.id)

    def test_project_not_found(self):
        """Test error when project doesn't exist."""
        with self.assertRaises(ToolError) as context:
            _resolve_project_for_job(self.owner, project='nonexistent')
        self.assertIn('not found', str(context.exception))

    def test_no_identifier_provided(self):
        """Test error when neither project nor project_id provided."""
        with self.assertRaises(ToolError) as context:
            _resolve_project_for_job(self.owner)
        self.assertIn("Either 'project'", str(context.exception))

    def test_unauthenticated_denied(self):
        """Test that unauthenticated users are denied."""
        with self.assertRaises(ToolError) as context:
            _resolve_project_for_job(None, project='test-project')
        self.assertIn('Authentication required', str(context.exception))


class TestJobManage(TestCase):
    """Tests for job_manage tool."""

    def setUp(self):
        """Create test user and project."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass'
        )
        self.shared_user = User.objects.create_user(
            username='shared',
            email='shared@test.com',
            password='testpass'
        )
        self.project = PathfinderProject.objects.create(
            user=self.user,
            name='test-project',
            repository_url='https://github.com/test/repo',
            status='pending'
        )
        self.project.shared_with.add(self.shared_user)

    @patch('mcp_server.tools.validate_elasticsearch_config')
    @patch('mcp_server.tools.trigger_indexer_job')
    def test_start_job_success(self, mock_trigger, mock_validate_es):
        """Test starting a job successfully."""
        mock_validate_es.return_value = (True, None)
        mock_trigger.return_value = (True, "Job started")

        result = job_manage(
            action='start',
            project='test-project',
            user=self.user
        )

        self.assertIn('Job Started', result)
        self.assertIn('test-project', result)
        mock_trigger.assert_called_once()

    @patch('mcp_server.tools.validate_elasticsearch_config')
    def test_start_job_es_not_configured(self, mock_validate_es):
        """Test starting job when ES not configured."""
        mock_validate_es.return_value = (False, "ES not configured")

        with self.assertRaises(ToolError) as context:
            job_manage(action='start', project='test-project', user=self.user)

        self.assertIn('Elasticsearch not configured', str(context.exception))

    def test_start_job_already_running(self):
        """Test starting a job that's already running."""
        self.project.status = 'running'
        self.project.save()

        with self.assertRaises(ToolError) as context:
            job_manage(action='start', project='test-project', user=self.user)

        self.assertIn('already has a running job', str(context.exception))

    def test_start_job_shared_user_denied(self):
        """Test that shared users cannot start jobs."""
        with self.assertRaises(ToolError) as context:
            job_manage(action='start', project='test-project', user=self.shared_user)

        self.assertIn('Read-only access', str(context.exception))

    @patch('mcp_server.tools.stop_indexer_job')
    def test_stop_job_success(self, mock_stop):
        """Test stopping a running job."""
        self.project.status = 'running'
        self.project.save()
        mock_stop.return_value = (True, "Job stopped")

        result = job_manage(action='stop', project='test-project', user=self.user)

        self.assertIn('Job Stopped', result)
        mock_stop.assert_called_once()

    def test_stop_job_not_running(self):
        """Test stopping a job that's not running."""
        self.project.status = 'completed'
        self.project.save()

        with self.assertRaises(ToolError) as context:
            job_manage(action='stop', project='test-project', user=self.user)

        self.assertIn('no running job', str(context.exception))

    def test_reset_job_success(self):
        """Test resetting a failed project."""
        self.project.status = 'failed'
        self.project.save()

        result = job_manage(action='reset', project='test-project', user=self.user)

        self.project.refresh_from_db()
        self.assertEqual(self.project.status, 'pending')
        self.assertIn('Project Reset', result)

    def test_reset_running_job_fails(self):
        """Test that running jobs cannot be reset."""
        self.project.status = 'running'
        self.project.save()

        with self.assertRaises(ToolError) as context:
            job_manage(action='reset', project='test-project', user=self.user)

        self.assertIn("while it's running", str(context.exception))

    def test_create_project_success(self):
        """Test creating a new project."""
        result = job_manage(
            action='create',
            repository_url='https://github.com/org/new-repo',
            name='new-project',
            user=self.user
        )

        self.assertIn('Project Created', result)
        self.assertIn('new-project', result)
        self.assertTrue(PathfinderProject.objects.filter(name='new-project').exists())

    def test_create_project_auto_name(self):
        """Test creating project with auto-generated name from URL."""
        result = job_manage(
            action='create',
            repository_url='https://github.com/org/auto-named-repo',
            user=self.user
        )

        self.assertIn('auto-named-repo', result)
        self.assertTrue(PathfinderProject.objects.filter(name='auto-named-repo').exists())

    def test_create_project_duplicate_name(self):
        """Test that duplicate project names are rejected."""
        with self.assertRaises(ToolError) as context:
            job_manage(
                action='create',
                repository_url='https://github.com/org/repo',
                name='test-project',  # Already exists
                user=self.user
            )

        self.assertIn('already exists', str(context.exception))

    def test_create_project_missing_url(self):
        """Test that repository_url is required for create."""
        with self.assertRaises(ToolError) as context:
            job_manage(action='create', name='my-project', user=self.user)

        self.assertIn('repository_url is required', str(context.exception))

    def test_update_project_success(self):
        """Test updating project settings."""
        result = job_manage(
            action='update',
            project='test-project',
            branch='develop',
            concurrency=8,
            user=self.user
        )

        self.project.refresh_from_db()
        self.assertEqual(self.project.branch, 'develop')
        self.assertEqual(self.project.concurrency, 8)
        self.assertIn('Project Updated', result)

    def test_update_project_invalid_concurrency(self):
        """Test that invalid concurrency is rejected."""
        with self.assertRaises(ToolError) as context:
            job_manage(
                action='update',
                project='test-project',
                concurrency=100,  # Too high
                user=self.user
            )

        self.assertIn('between 1 and 16', str(context.exception))

    @patch('mcp_server.tools.get_es_client')
    @patch('mcp_server.tools.stop_indexer_job')
    def test_delete_project_success(self, mock_stop, mock_es):
        """Test deleting a project."""
        mock_es.return_value = MagicMock()
        mock_stop.return_value = (True, "Stopped")

        project_id = self.project.id
        result = job_manage(action='delete', project='test-project', user=self.user)

        self.assertIn('Project Deleted', result)
        self.assertFalse(PathfinderProject.objects.filter(id=project_id).exists())

    def test_delete_project_not_owner(self):
        """Test that non-owners cannot delete projects."""
        with self.assertRaises(ToolError) as context:
            job_manage(action='delete', project='test-project', user=self.shared_user)

        self.assertIn('Read-only access', str(context.exception))

    @patch('mcp_server.tools.validate_elasticsearch_config')
    @patch('mcp_server.tools.trigger_indexer_job')
    def test_bulk_start_success(self, mock_trigger, mock_validate_es):
        """Test bulk starting multiple projects."""
        mock_validate_es.return_value = (True, None)
        mock_trigger.return_value = (True, "Job started")

        # Create another project
        project2 = PathfinderProject.objects.create(
            user=self.user,
            name='test-project-2',
            repository_url='https://github.com/test/repo2',
            status='pending'
        )

        result = job_manage(
            action='bulk_start',
            project_ids=[self.project.id, project2.id],
            user=self.user
        )

        self.assertIn('Bulk Start Results', result)
        self.assertIn('Started: 2/2', result)

    @patch('mcp_server.tools.stop_indexer_job')
    def test_bulk_stop_success(self, mock_stop):
        """Test bulk stopping multiple projects."""
        mock_stop.return_value = (True, "Stopped")

        self.project.status = 'running'
        self.project.save()

        project2 = PathfinderProject.objects.create(
            user=self.user,
            name='test-project-2',
            repository_url='https://github.com/test/repo2',
            status='running'
        )

        result = job_manage(
            action='bulk_stop',
            project_ids=[self.project.id, project2.id],
            user=self.user
        )

        self.assertIn('Bulk Stop Results', result)
        self.assertIn('Stopped: 2/2', result)

    def test_unknown_action(self):
        """Test that unknown actions raise ToolError."""
        with self.assertRaises(ToolError) as context:
            job_manage(action='unknown', project='test-project', user=self.user)

        self.assertIn('Unknown action', str(context.exception))


class TestJobStatus(TestCase):
    """Tests for job_status tool."""

    def setUp(self):
        """Create test user and project."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass'
        )
        self.project = PathfinderProject.objects.create(
            user=self.user,
            name='test-project',
            repository_url='https://github.com/test/repo',
            status='completed',
            custom_index_name='project-test'
        )

    @patch('mcp_server.tools._get_index_stats')
    def test_status_action(self, mock_stats):
        """Test getting project status."""
        mock_stats.return_value = {'document_count': 1000, 'index_size_mb': 5.5}

        result = job_status(action='status', project='test-project', user=self.user)

        self.assertIn('Project Status', result)
        self.assertIn('test-project', result)
        self.assertIn('completed', result)

    def test_list_action(self):
        """Test listing all projects."""
        result = job_status(action='list', user=self.user)

        self.assertIn('Projects', result)
        self.assertIn('test-project', result)

    def test_list_with_filter(self):
        """Test listing projects with status filter."""
        result = job_status(action='list', status_filter='completed', user=self.user)

        self.assertIn('test-project', result)

    def test_list_empty_filter(self):
        """Test listing with filter that matches nothing."""
        result = job_status(action='list', status_filter='running', user=self.user)

        self.assertIn("No projects found with status 'running'", result)

    def test_details_action(self):
        """Test getting project details."""
        result = job_status(action='details', project='test-project', user=self.user)

        self.assertIn('Project Details', result)
        self.assertIn('test-project', result)
        self.assertIn('https://github.com/test/repo', result)

    @patch('mcp_server.tools._get_job_logs')
    def test_logs_action(self, mock_logs):
        """Test getting project logs."""
        mock_logs.return_value = [
            {'timestamp': '2024-01-01T00:00:00', 'level': 'INFO', 'message': 'Test log'}
        ]

        result = job_status(action='logs', project='test-project', user=self.user)

        self.assertIn('Logs for test-project', result)
        self.assertIn('Test log', result)

    def test_logs_no_logs(self):
        """Test logs when no logs available."""
        with patch('mcp_server.tools._get_job_logs', return_value=[]):
            result = job_status(action='logs', project='test-project', user=self.user)

        self.assertIn('No logs available', result)

    def test_history_action(self):
        """Test getting job history."""
        from django.utils import timezone
        JobRun.objects.create(
            project=self.project,
            job_id='test-job-1',
            started_at=timezone.now(),
            final_status='completed',
            options={'clean_index': True},
            result={'files_indexed': 100}
        )

        result = job_status(action='history', project='test-project', user=self.user)

        self.assertIn('Job History', result)
        self.assertIn('completed', result)

    def test_history_no_runs(self):
        """Test history when no job runs exist."""
        result = job_status(action='history', project='test-project', user=self.user)

        self.assertIn('No job runs recorded', result)

    def test_unknown_action(self):
        """Test that unknown actions raise ToolError."""
        with self.assertRaises(ToolError) as context:
            job_status(action='unknown', project='test-project', user=self.user)

        self.assertIn('Unknown action', str(context.exception))

    def test_unauthenticated_denied(self):
        """Test that unauthenticated users are denied."""
        with self.assertRaises(ToolError) as context:
            job_status(action='list', user=None)

        self.assertIn('Authentication required', str(context.exception))


class TestGetIndexStats(TestCase):
    """Tests for _get_index_stats helper function."""

    def setUp(self):
        """Create test project."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass'
        )
        self.project = PathfinderProject.objects.create(
            user=self.user,
            name='test-project',
            repository_url='https://github.com/test/repo',
            custom_index_name='project-test'
        )

    @patch('mcp_server.tools.get_es_client')
    def test_get_stats_success(self, mock_es_client):
        """Test getting index stats successfully."""
        mock_es = MagicMock()
        mock_es.indices.stats.return_value = {
            'indices': {
                'project-test': {
                    'primaries': {
                        'docs': {'count': 1000},
                        'store': {'size_in_bytes': 1024 * 1024 * 5}  # 5 MB
                    }
                }
            }
        }
        mock_es_client.return_value = mock_es

        result = _get_index_stats(self.project)

        self.assertEqual(result['document_count'], 1000)
        self.assertEqual(result['index_size_mb'], 5.0)

    @patch('mcp_server.tools.get_es_client')
    def test_get_stats_no_client(self, mock_es_client):
        """Test handling when ES client is not available."""
        mock_es_client.return_value = None

        result = _get_index_stats(self.project)

        self.assertIsNone(result)

    def test_get_stats_no_index(self):
        """Test handling when project has no index name."""
        self.project.custom_index_name = None
        self.project.save()

        result = _get_index_stats(self.project)

        self.assertIsNone(result)

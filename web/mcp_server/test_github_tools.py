"""
Tests for enhanced GitHub tools in MCP Server.

Tests cover:
1. github_create_issue with templates and draft mode
2. github_get_labels tool
3. _format_issue_body helper function

Run with:
    docker-compose exec web python manage.py test mcp_server.test_github_tools

Or manually via shell:
    docker-compose exec web python manage.py shell < mcp_server/test_github_tools.py
"""

import unittest
from unittest.mock import MagicMock, patch
from mcp_server.tools import (
    _format_issue_body,
    github_manage_issues,
    github_manage_code,
    ToolError
)


class TestFormatIssueBody(unittest.TestCase):
    """Test the _format_issue_body helper function."""

    def test_general_issue_uses_body_as_is(self):
        """General issues should use the body without modifications."""
        result = _format_issue_body(
            summary="This is a general issue description.",
            issue_type="general"
        )
        self.assertIn("This is a general issue description.", result)
        self.assertIn("Created via CodePathfinder", result)
        # Should NOT have section headers for general issues
        self.assertNotIn("## Summary", result)

    def test_bug_template_formatting(self):
        """Bug reports should include all bug-specific sections."""
        result = _format_issue_body(
            summary="Authentication fails on login",
            issue_type="bug",
            steps_to_reproduce="1. Go to login page\n2. Enter credentials\n3. Click submit",
            expected_behavior="User should be logged in",
            actual_behavior="Error message appears",
            environment="Chrome 120, macOS 14"
        )

        self.assertIn("## Summary", result)
        self.assertIn("Authentication fails on login", result)
        self.assertIn("## Steps to Reproduce", result)
        self.assertIn("1. Go to login page", result)
        self.assertIn("## Expected Behavior", result)
        self.assertIn("User should be logged in", result)
        self.assertIn("## Actual Behavior", result)
        self.assertIn("Error message appears", result)
        self.assertIn("## Environment", result)
        self.assertIn("Chrome 120, macOS 14", result)

    def test_feature_template_formatting(self):
        """Feature requests should include all feature-specific sections."""
        result = _format_issue_body(
            summary="Add dark mode support",
            issue_type="feature",
            use_case="Users want to reduce eye strain at night",
            proposed_solution="Add a theme toggle in settings",
            alternatives_considered="Browser extension, OS-level dark mode"
        )

        self.assertIn("## Summary", result)
        self.assertIn("Add dark mode support", result)
        self.assertIn("## Use Case", result)
        self.assertIn("Users want to reduce eye strain", result)
        self.assertIn("## Proposed Solution", result)
        self.assertIn("Add a theme toggle", result)
        self.assertIn("## Alternatives Considered", result)
        self.assertIn("Browser extension", result)

    def test_bug_with_partial_fields(self):
        """Bug reports should work with only some optional fields."""
        result = _format_issue_body(
            summary="API returns 500 error",
            issue_type="bug",
            steps_to_reproduce="Call GET /api/users"
        )

        self.assertIn("## Summary", result)
        self.assertIn("## Steps to Reproduce", result)
        # Missing fields should not appear
        self.assertNotIn("## Expected Behavior", result)
        self.assertNotIn("## Actual Behavior", result)

    def test_code_references_formatting(self):
        """Code references should be formatted in a Related Code section."""
        result = _format_issue_body(
            summary="Bug in authentication",
            issue_type="bug",
            code_references=[
                {
                    "file_path": "src/auth/login.py",
                    "line_start": 42,
                    "line_end": 50,
                    "snippet": "def authenticate(user):\n    return True",
                    "description": "The authentication function"
                },
                {
                    "file_path": "src/utils/helpers.ts",
                    "line_start": 10,
                    "snippet": "export function helper() { return true; }",
                    "description": "Helper function"
                }
            ]
        )

        self.assertIn("## Related Code", result)
        self.assertIn("**`src/auth/login.py` (lines 42-50)**", result)
        self.assertIn("```py", result)  # Language detection from extension
        self.assertIn("def authenticate(user):", result)
        self.assertIn("**`src/utils/helpers.ts` (line 10)**", result)
        self.assertIn("```ts", result)  # Language detection from extension
        self.assertIn("export function helper()", result)

    def test_code_references_without_line_numbers(self):
        """Code references without line numbers should work."""
        result = _format_issue_body(
            summary="Issue description",
            issue_type="general",
            code_references=[
                {"file_path": "README.md"}
            ]
        )

        self.assertIn("## Related Code", result)
        self.assertIn("**`README.md`**", result)


class TestGitHubCreateIssue(unittest.TestCase):
    """Test the github_create_issue tool."""

    def test_draft_mode_returns_preview(self):
        """Draft mode should return a preview without creating the issue."""
        result = github_manage_issues(
            action="create_issue",
            project_name="test-project",
            title="Test Issue",
            body="This is a test issue",
            labels=["bug", "high-priority"],
            issue_type="bug",
            draft=True,
            steps_to_reproduce="1. Do something",
            user=None  # Will fail auth but draft mode doesn't need it
        )

        # Draft mode should return preview without attempting GitHub API
        self.assertIn("Issue Preview (Draft Mode)", result)
        self.assertIn("Test Issue", result)
        self.assertIn("bug, high-priority", result)
        self.assertIn("## Summary", result)
        self.assertIn("This is a test issue", result)
        self.assertIn("## Steps to Reproduce", result)
        self.assertIn("draft=false", result)

    def test_draft_mode_shows_issue_type(self):
        """Draft preview should show the issue type."""
        result = github_manage_issues(
            action="create_issue",
            project_name="test",
            title="Feature Request",
            body="Add feature X",
            issue_type="feature",
            draft=True,
            user=None
        )

        self.assertIn("**Type:** Feature", result)

    def test_draft_mode_with_code_references(self):
        """Draft mode should include code references."""
        result = github_manage_issues(
            action="create_issue",
            project_name="test",
            title="Bug with code",
            body="Found a bug",
            issue_type="bug",
            draft=True,
            code_references=[
                {
                    "file_path": "src/main.py",
                    "line_start": 10,
                    "snippet": "print('hello')"
                }
            ],
            user=None
        )

        self.assertIn("## Related Code", result)
        self.assertIn("src/main.py", result)
        self.assertIn("print('hello')", result)

    @patch('mcp_server.tools._get_project_for_github')
    @patch('mcp_server.tools.GitHubService')
    def test_create_issue_calls_github_service(self, mock_github_service, mock_get_project):
        """Creating an issue should call GitHubService with formatted body."""
        # Setup mocks
        mock_project = MagicMock()
        mock_get_project.return_value = mock_project

        mock_service = MagicMock()
        mock_github_service.return_value = mock_service

        mock_issue = MagicMock()
        mock_issue.number = 123
        mock_issue.title = "Test Issue"
        mock_issue.html_url = "https://github.com/test/repo/issues/123"
        mock_issue.state = "open"
        mock_issue.labels = []
        mock_service.create_issue.return_value = mock_issue

        mock_user = MagicMock()
        mock_user.is_authenticated = True

        result = github_manage_issues(
            action="create_issue",
            project_name="test-project",
            title="Test Issue",
            body="Bug description",
            labels=["bug"],
            issue_type="bug",
            steps_to_reproduce="1. Do this",
            user=mock_user
        )

        # Verify the issue was created
        self.assertIn("Issue created successfully!", result)
        self.assertIn("#123", result)
        self.assertIn("https://github.com/test/repo/issues/123", result)

        # Verify GitHubService was called with formatted body
        call_args = mock_service.create_issue.call_args
        created_title = call_args[0][0]
        created_body = call_args[0][1]

        self.assertEqual(created_title, "Test Issue")
        self.assertIn("## Summary", created_body)
        self.assertIn("Bug description", created_body)
        self.assertIn("## Steps to Reproduce", created_body)

    def test_create_without_auth_raises_error(self):
        """Creating an issue without authentication should raise ToolError."""
        with self.assertRaises(ToolError):
            github_manage_issues(
                action="create_issue",
                project_name="test",
                title="Test",
                body="Test body",
                draft=False,  # Actual creation requires auth
                user=None
            )


class TestGitHubGetLabels(unittest.TestCase):
    """Test the github_get_labels tool."""

    @patch('mcp_server.tools._get_project_for_github')
    @patch('mcp_server.tools.GitHubService')
    def test_returns_formatted_labels(self, mock_github_service, mock_get_project):
        """Should return formatted list of available labels."""
        mock_project = MagicMock()
        mock_get_project.return_value = mock_project

        mock_service = MagicMock()
        mock_github_service.return_value = mock_service
        mock_service.list_labels.return_value = [
            {"name": "bug", "color": "d73a4a", "description": "Something isn't working"},
            {"name": "enhancement", "color": "a2eeef", "description": "New feature or request"},
            {"name": "documentation", "color": "0075ca", "description": ""}
        ]

        mock_user = MagicMock()
        mock_user.is_authenticated = True

        result = github_manage_issues(
            action="get_labels",
            project_name="test-project",
            user=mock_user
        )

        self.assertIn("Available labels for test-project:", result)
        self.assertIn("bug", result)
        self.assertIn("Something isn't working", result)
        self.assertIn("enhancement", result)
        self.assertIn("New feature or request", result)
        self.assertIn("documentation", result)
        self.assertIn("Total: 3 labels", result)

    @patch('mcp_server.tools._get_project_for_github')
    @patch('mcp_server.tools.GitHubService')
    def test_handles_empty_labels(self, mock_github_service, mock_get_project):
        """Should return helpful message when no labels are configured."""
        mock_project = MagicMock()
        mock_get_project.return_value = mock_project

        mock_service = MagicMock()
        mock_github_service.return_value = mock_service
        mock_service.list_labels.return_value = []

        mock_user = MagicMock()
        mock_user.is_authenticated = True

        result = github_manage_issues(
            action="get_labels",
            project_name="test-project",
            user=mock_user
        )

        self.assertIn("No labels configured for test-project", result)

    def test_requires_authentication(self):
        """Should raise ToolError when not authenticated."""
        with self.assertRaises(ToolError):
            github_manage_issues(
                action="get_labels",
                project_name="test",
                user=None
            )


class TestGitHubGetLatestChanges(unittest.TestCase):
    """Test the github_get_latest_changes tool."""

    @patch('mcp_server.tools._get_project_for_github')
    @patch('mcp_server.tools.GitHubService')
    def test_returns_recent_commits(self, mock_github_service, mock_get_project):
        """Should return formatted list of recent commits."""
        mock_project = MagicMock()
        mock_get_project.return_value = mock_project

        mock_service = MagicMock()
        mock_github_service.return_value = mock_service
        mock_service.get_recent_commits.return_value = [
            {
                "sha": "a1b2c3d4e5f6",
                "author": "Alice",
                "date": "2023-10-01T12:00:00Z",
                "message": "Fix login bug",
                "html_url": "https://github.com/test/repo/commit/a1b2"
            },
            {
                "sha": "1234567890ab",
                "author": "Bob",
                "date": "2023-10-02T14:30:00Z",
                "message": "Add new feature\n\nMore details here",
                "html_url": "https://github.com/test/repo/commit/1234"
            }
        ]
        mock_service.get_repo_info.return_value = {"default_branch": "main"}

        mock_user = MagicMock()
        mock_user.is_authenticated = True

        result = github_manage_code(
            action="latest_changes",
            project_name="test-project",
            user=mock_user
        )

        self.assertIn("Recent commits for project 'test-project' (branch: main):", result)
        self.assertIn("- [a1b2c3d] 2023-10-01 - Fix login bug (Alice)", result)
        self.assertIn("- [1234567] 2023-10-02 - Add new feature (Bob)", result)

    @patch('mcp_server.tools._get_project_for_github')
    @patch('mcp_server.tools.GitHubService')
    def test_handles_no_commits(self, mock_github_service, mock_get_project):
        """Should return helpful message when no commits are found."""
        mock_project = MagicMock()
        mock_get_project.return_value = mock_project

        mock_service = MagicMock()
        mock_github_service.return_value = mock_service
        mock_service.get_recent_commits.return_value = []

        mock_user = MagicMock()
        mock_user.is_authenticated = True

        result = github_manage_code(
            action="latest_changes",
            project_name="test-project",
            user=mock_user
        )

        self.assertIn("No recent commits found for project 'test-project'", result)


if __name__ == '__main__':
    # When run via Django shell, use unittest directly
    import sys

    # Check if running in Django shell context
    try:
        from django.conf import settings
        if settings.configured:
            print("=" * 80)
            print("Running GitHub Tools Tests")
            print("=" * 80)

            loader = unittest.TestLoader()
            suite = unittest.TestSuite()

            suite.addTests(loader.loadTestsFromTestCase(TestFormatIssueBody))
            suite.addTests(loader.loadTestsFromTestCase(TestGitHubCreateIssue))
            suite.addTests(loader.loadTestsFromTestCase(TestGitHubGetLabels))
            suite.addTests(loader.loadTestsFromTestCase(TestGitHubGetLatestChanges))

            runner = unittest.TextTestRunner(verbosity=2)
            result = runner.run(suite)

            print("\n" + "=" * 80)
            if result.wasSuccessful():
                print("All tests passed!")
            else:
                print(f"Tests failed: {len(result.failures)} failures, {len(result.errors)} errors")
            print("=" * 80)
    except Exception as e:
        # Standard unittest run
        unittest.main()

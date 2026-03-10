"""
GitHub Service for CodePathfinder.

Provides PyGithub wrapper with permission checks for write operations
on project repositories.
"""
import re
from github import Github, GithubException

from .models import PathfinderProject


class GitHubPermissionError(Exception):
    """Raised when user lacks permission for GitHub operation."""
    pass


class GitHubService:
    """
    Service for GitHub API operations with permission validation.

    Token resolution order:
    1. User's personal GitHub token (from UserGitHubSettings)
    2. Project's GitHub token (configured during project setup)

    Validates:
    - A GitHub token is available (user or project level)
    - Project is in allowed status (completed, watching, stopped)
    - User has access to project (owner or shared_with)
    """

    ALLOWED_STATUSES = ['completed', 'watching', 'stopped']

    def __init__(self, user, project):
        """
        Initialize GitHub service for a user and project.

        Args:
            user: Django User instance
            project: PathfinderProject instance

        Raises:
            GitHubPermissionError: If validation fails
        """
        self.user = user
        self.project = project
        self._github_token = None  # Will be set during validation
        self._validate_permissions()
        self._init_github_client()

    def _get_github_token(self):
        """
        Get GitHub token from user settings or project configuration.

        Resolution order:
        1. User's personal GitHub token (UserGitHubSettings.github_token)
        2. Project's GitHub token (PathfinderProject.github_token)

        Returns:
            str: GitHub token or None if not configured
        """
        # First, try user's personal GitHub token
        github_settings = getattr(self.user, 'github_settings', None)
        if github_settings and github_settings.github_token:
            return github_settings.github_token

        # Fall back to project's GitHub token
        if self.project.github_token:
            return self.project.github_token

        return None

    def _validate_permissions(self):
        """Validate user has permission to perform GitHub operations."""
        # Check for GitHub token (user-level or project-level)
        self._github_token = self._get_github_token()
        if not self._github_token:
            raise GitHubPermissionError(
                "No GitHub token configured. Please add a GitHub Personal Access Token in your "
                "profile settings or configure one in the project settings."
            )

        # Check project status
        if self.project.status not in self.ALLOWED_STATUSES:
            raise GitHubPermissionError(
                f"GitHub operations require project status to be one of: {', '.join(self.ALLOWED_STATUSES)}. "
                f"Current status: {self.project.status}"
            )

        # Check user access to project
        is_owner = self.project.user == self.user
        is_shared = self.project.shared_with.filter(pk=self.user.pk).exists()
        if not is_owner and not is_shared:
            raise GitHubPermissionError("You do not have access to this project.")

    def _init_github_client(self):
        """Initialize PyGithub client and repository."""
        try:
            self.github = Github(self._github_token)
            # Validate token by fetching authenticated user
            self._authenticated_user = self.github.get_user().login
        except GithubException as e:
            raise GitHubPermissionError(f"GitHub token invalid or expired: {e.data.get('message', str(e))}")

        self.repo = self._get_repo()

    def _get_repo(self):
        """Parse repository URL and get PyGithub Repository object."""
        url = self.project.repository_url.rstrip('/')

        # Remove .git suffix if present
        if url.endswith('.git'):
            url = url[:-4]

        # Handle both HTTPS and SSH formats
        # HTTPS: https://github.com/owner/repo
        # SSH: git@github.com:owner/repo
        if 'github.com:' in url:
            # SSH format: git@github.com:owner/repo
            match = re.search(r'github\.com:([^/]+)/(.+)', url)
            if match:
                owner, repo_name = match.groups()
            else:
                raise GitHubPermissionError(f"Invalid GitHub SSH URL format: {url}")
        else:
            # HTTPS format: https://github.com/owner/repo
            parts = url.split('/')
            if len(parts) < 2:
                raise GitHubPermissionError(f"Invalid GitHub URL format: {url}")
            owner, repo_name = parts[-2], parts[-1]

        try:
            return self.github.get_repo(f"{owner}/{repo_name}")
        except GithubException as e:
            raise GitHubPermissionError(
                f"Cannot access repository {owner}/{repo_name}: {e.data.get('message', str(e))}"
            )

    # Issue Operations

    def create_issue(self, title, body, labels=None):
        """
        Create a new issue on the repository.

        Args:
            title: Issue title
            body: Issue body/description
            labels: Optional list of label names

        Returns:
            PyGithub Issue object
        """
        try:
            return self.repo.create_issue(title=title, body=body, labels=labels or [])
        except GithubException as e:
            raise GitHubPermissionError(f"Failed to create issue: {e.data.get('message', str(e))}")

    def get_issue(self, issue_number):
        """
        Get an issue by number.

        Args:
            issue_number: Issue number

        Returns:
            PyGithub Issue object
        """
        try:
            return self.repo.get_issue(issue_number)
        except GithubException as e:
            raise GitHubPermissionError(f"Failed to get issue #{issue_number}: {e.data.get('message', str(e))}")

    def add_comment(self, issue_number, body):
        """
        Add a comment to an issue or pull request.

        Args:
            issue_number: Issue/PR number
            body: Comment body

        Returns:
            PyGithub IssueComment object
        """
        try:
            issue = self.repo.get_issue(issue_number)
            return issue.create_comment(body)
        except GithubException as e:
            raise GitHubPermissionError(f"Failed to add comment: {e.data.get('message', str(e))}")

    # Pull Request Operations

    def create_pull_request(self, title, body, head, base='main'):
        """
        Create a new pull request.

        Args:
            title: PR title
            body: PR body/description
            head: Head branch name
            base: Base branch name (default: main)

        Returns:
            PyGithub PullRequest object
        """
        try:
            return self.repo.create_pull(title=title, body=body, head=head, base=base)
        except GithubException as e:
            raise GitHubPermissionError(f"Failed to create pull request: {e.data.get('message', str(e))}")

    def get_pull_request(self, pr_number):
        """
        Get a pull request by number.

        Args:
            pr_number: Pull request number

        Returns:
            PyGithub PullRequest object
        """
        try:
            return self.repo.get_pull(pr_number)
        except GithubException as e:
            raise GitHubPermissionError(f"Failed to get PR #{pr_number}: {e.data.get('message', str(e))}")

    # Branch Operations

    def create_branch(self, branch_name, from_ref='main'):
        """
        Create a new branch from an existing ref.

        Args:
            branch_name: New branch name
            from_ref: Source branch/ref (default: main)

        Returns:
            PyGithub GitRef object
        """
        try:
            source = self.repo.get_branch(from_ref)
            return self.repo.create_git_ref(f"refs/heads/{branch_name}", source.commit.sha)
        except GithubException as e:
            raise GitHubPermissionError(f"Failed to create branch: {e.data.get('message', str(e))}")

    def list_branches(self):
        """
        List all branches in the repository.

        Returns:
            List of branch names
        """
        try:
            return [b.name for b in self.repo.get_branches()]
        except GithubException as e:
            raise GitHubPermissionError(f"Failed to list branches: {e.data.get('message', str(e))}")

    def get_default_branch(self):
        """
        Get the default branch name.

        Returns:
            Default branch name (e.g., 'main' or 'master')
        """
        return self.repo.default_branch

    # Label Operations

    def list_labels(self):
        """
        List all labels in the repository.

        Returns:
            List of dicts with 'name', 'color', 'description'
        """
        try:
            labels = self.repo.get_labels()
            return [
                {
                    'name': label.name,
                    'color': label.color,
                    'description': label.description or ''
                }
                for label in labels
            ]
        except GithubException as e:
            raise GitHubPermissionError(f"Failed to list labels: {e.data.get('message', str(e))}")

    # Repository Information

    def get_repo_info(self):
        """
        Get repository information.

        Returns:
            Dict with repository details
        """
        return {
            'name': self.repo.name,
            'full_name': self.repo.full_name,
            'description': self.repo.description,
            'default_branch': self.repo.default_branch,
            'private': self.repo.private,
            'html_url': self.repo.html_url,
        }

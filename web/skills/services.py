"""
Skills Service for CodePathfinder.

Handles bi-directional skill syncing with GitHub repositories and skill retrieval.
"""
import logging
import re
from django.utils import timezone

import yaml
from github import Github, GithubException

from core.models import SystemSettings
from .models import Skill

logger = logging.getLogger(__name__)


class SkillSyncError(Exception):
    """Raised when skill sync fails."""
    pass


class SkillPushError(Exception):
    """Raised when pushing skill to GitHub fails."""
    pass


class SkillService:
    """
    Service for managing AI agent skills.

    Provides:
    - SKILL.md parsing (YAML frontmatter + markdown instructions)
    - GitHub repository syncing with timestamp-based conflict resolution
    - Skill retrieval by name or search
    """

    def __init__(self):
        self.settings = SystemSettings.get_settings()

    def _get_github_file_timestamp(self, repo, file_path, branch):
        """
        Get the last commit timestamp for a file in GitHub.

        Args:
            repo: PyGithub Repository object
            file_path: Path to the file (e.g., 'skills/code-review/SKILL.md')
            branch: Branch name

        Returns:
            timezone-aware datetime of last commit, or None if file doesn't exist
        """
        try:
            commits = repo.get_commits(path=file_path, sha=branch)
            # Get the most recent commit for this file
            for commit in commits:
                # commit.commit.author.date is already a datetime object
                commit_date = commit.commit.author.date
                # Ensure timezone-aware (GitHub returns UTC)
                if commit_date.tzinfo is None:
                    from datetime import timezone as dt_timezone
                    commit_date = commit_date.replace(tzinfo=dt_timezone.utc)
                return commit_date
        except GithubException as e:
            logger.debug(f"Could not get commit history for {file_path}: {e}")
        return None

    def parse_skill_md(self, content):
        """
        Parse a SKILL.md file with YAML frontmatter.

        Format:
        ```
        ---
        name: skill-name
        description: Brief description
        allowed-tools:
          - tool1
          - tool2
        tags:
          - tag1
          - tag2
        ---
        # Instructions

        Full instructions for the AI agent...
        ```

        Args:
            content: Raw SKILL.md file content

        Returns:
            Dict with parsed skill data

        Raises:
            ValueError: If format is invalid
        """
        # Match YAML frontmatter between --- markers
        pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(pattern, content, re.DOTALL)

        if not match:
            raise ValueError(
                "Invalid SKILL.md format. Expected YAML frontmatter between --- markers."
            )

        frontmatter_str = match.group(1)
        instructions = match.group(2).strip()

        try:
            frontmatter = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in frontmatter: {e}")

        if not frontmatter:
            raise ValueError("Empty frontmatter in SKILL.md")

        # Validate required fields
        if not frontmatter.get('name'):
            raise ValueError("SKILL.md missing required 'name' field")
        if not frontmatter.get('description'):
            raise ValueError("SKILL.md missing required 'description' field")

        return {
            'name': frontmatter.get('name'),
            'description': frontmatter.get('description', ''),
            'allowed_tools': frontmatter.get('allowed-tools', []),
            'tags': frontmatter.get('tags', []),
            'instructions': instructions,
            'hidden': frontmatter.get('hidden', False),
            'curated': frontmatter.get('curated', False),
        }

    def _validate_skill_data(self, skill_data):
        """Validate parsed skill data has required fields."""
        required = ['name', 'description', 'instructions']
        missing = [f for f in required if not skill_data.get(f)]
        if missing:
            raise ValueError(f"Skill missing required fields: {', '.join(missing)}")

    def export_skill_to_md(self, skill):
        """
        Export a Skill object to SKILL.md format.

        Args:
            skill: Skill model instance

        Returns:
            String content in SKILL.md format
        """
        # Build frontmatter
        frontmatter = {
            'name': skill.name,
            'description': skill.description,
        }

        if skill.allowed_tools:
            frontmatter['allowed-tools'] = skill.allowed_tools

        if skill.tags:
            frontmatter['tags'] = skill.tags

        if skill.is_curated:
            frontmatter['curated'] = True

        # Mark as hidden if skill was deleted (soft-deleted)
        if skill.is_hidden:
            frontmatter['hidden'] = True

        # Convert to YAML
        frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Build full SKILL.md content
        content = f"---\n{frontmatter_str}---\n\n{skill.instructions}"

        return content

    def _get_github_client_and_repo(self):
        """
        Get authenticated GitHub client and repository.
        
        Returns:
            Tuple of (repo, branch) or raises SkillSyncError
        """
        if not self.settings.skills_repo_url:
            raise SkillSyncError("No skills repository URL configured")

        token = self.settings.skills_repo_token
        if not token:
            raise SkillSyncError("GitHub token required for push operations")
        
        github = Github(token)

        # Parse repo from URL
        url = self.settings.skills_repo_url.rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]

        parts = url.split('/')
        if len(parts) < 2:
            raise SkillSyncError(f"Invalid repository URL: {self.settings.skills_repo_url}")

        owner, repo_name = parts[-2], parts[-1]

        try:
            repo = github.get_repo(f"{owner}/{repo_name}")
        except GithubException as e:
            raise SkillSyncError(f"Cannot access repository: {e.data.get('message', str(e))}")

        branch = self.settings.skills_repo_branch or 'main'
        return repo, branch

    def push_skill_to_github(self, skill):
        """
        Push a single skill to GitHub repository.

        Creates or updates the skill directory and SKILL.md file.

        Args:
            skill: Skill model instance

        Returns:
            Updated github_path

        Raises:
            SkillPushError: If push fails
        """
        repo, branch = self._get_github_client_and_repo()
        
        # Determine skill directory name (kebab-case)
        skill_dir_name = skill.name.lower().replace(' ', '-').replace('_', '-')
        skill_md_path = f"skills/{skill_dir_name}/SKILL.md"
        
        # Export skill to SKILL.md format
        content = self.export_skill_to_md(skill)
        
        try:
            # Check if file already exists
            try:
                existing_file = repo.get_contents(skill_md_path, ref=branch)
                # Update existing file
                repo.update_file(
                    path=skill_md_path,
                    message=f"Update skill: {skill.name}",
                    content=content,
                    sha=existing_file.sha,
                    branch=branch
                )
                logger.info(f"Updated skill in GitHub: {skill_md_path}")
            except GithubException as e:
                if e.status == 404:
                    # Create new file
                    repo.create_file(
                        path=skill_md_path,
                        message=f"Add skill: {skill.name}",
                        content=content,
                        branch=branch
                    )
                    logger.info(f"Created skill in GitHub: {skill_md_path}")
                else:
                    raise
            
            # Also push context files if any
            if skill.context_files:
                for filename, file_content in skill.context_files.items():
                    context_path = f"skills/{skill_dir_name}/{filename}"
                    try:
                        existing = repo.get_contents(context_path, ref=branch)
                        repo.update_file(
                            path=context_path,
                            message=f"Update context file for {skill.name}: {filename}",
                            content=file_content,
                            sha=existing.sha,
                            branch=branch
                        )
                    except GithubException as e:
                        if e.status == 404:
                            repo.create_file(
                                path=context_path,
                                message=f"Add context file for {skill.name}: {filename}",
                                content=file_content,
                                branch=branch
                            )
                        else:
                            logger.warning(f"Failed to push context file {filename}: {e}")

            # Update skill's github_path
            skill.github_path = skill_md_path
            skill.last_synced = timezone.now()
            skill.save(update_fields=['github_path', 'last_synced'])
            
            return skill_md_path

        except GithubException as e:
            raise SkillPushError(f"Failed to push skill to GitHub: {e.data.get('message', str(e))}")

    def sync_skills(self):
        """
        Bi-directional sync: Pull from GitHub AND push local skills to GitHub.

        1. Pull all skills from GitHub repository to database
        2. Push all database skills (without github_path or modified) to GitHub

        Returns:
            Dict with sync results: {'pulled': [...], 'pushed': [...], 'errors': [...]}

        Raises:
            SkillSyncError: If sync fails completely
        """
        results = {
            'pulled': [],
            'pushed': [],
            'errors': []
        }

        # Phase 1: Pull from GitHub
        try:
            pulled = self._pull_from_github()
            results['pulled'] = pulled
        except SkillSyncError as e:
            results['errors'].append(f"Pull failed: {str(e)}")
            # Continue to push phase even if pull fails

        # Phase 2: Push local skills to GitHub
        try:
            pushed = self._push_to_github()
            results['pushed'] = pushed
        except SkillSyncError as e:
            results['errors'].append(f"Push failed: {str(e)}")

        return results

    def _pull_from_github(self):
        """Pull skills from GitHub to database and prune orphaned skills.
        
        Skills are pruned (deactivated) if:
        1. Their github_path directory no longer exists in GitHub
        2. Their github_path maps to a different skill (duplicate case)
        """
        repo, branch = self._get_github_client_and_repo()

        # Get contents of skills directory
        try:
            contents = repo.get_contents("skills", ref=branch)
        except GithubException as e:
            if e.status == 404:
                # Skills directory doesn't exist yet, that's OK
                logger.info("No 'skills' directory in GitHub repo yet")
                return []
            raise SkillSyncError(f"Cannot access 'skills' directory: {e.data.get('message', str(e))}")

        synced = []
        # Track which GitHub directories exist and which skill ID they map to
        github_dirs = set()  # e.g., {"skills/code-review", "skills/documentation-writer"}
        dir_to_skill_id = {}  # e.g., {"skills/code-review": 5, ...}

        for item in contents:
            if item.type == "dir":
                github_dirs.add(item.path)
                try:
                    skill = self._process_skill_dir(repo, item.path, branch)
                    if skill:
                        synced.append(skill.name)
                        dir_to_skill_id[item.path] = skill.id
                except Exception as e:
                    logger.warning(f"Failed to sync skill from {item.path}: {e}")

        # Prune orphaned skills: deactivate skills whose github_path no longer exists
        # or whose github_path now maps to a different skill (duplicate case)
        pruned = self._prune_orphaned_skills(github_dirs, dir_to_skill_id)
        if pruned:
            logger.info(f"Pruned {len(pruned)} orphaned skills: {pruned}")

        logger.info(f"Pulled {len(synced)} skills from GitHub")
        return synced

    def _prune_orphaned_skills(self, github_dirs, dir_to_skill_id):
        """Deactivate skills that are no longer present in GitHub or are duplicates.
        
        Args:
            github_dirs: Set of directory paths that exist in GitHub (e.g., "skills/code-review")
            dir_to_skill_id: Dict mapping directory path to the skill ID that was synced from it
            
        Returns:
            List of pruned skill names
        """
        pruned = []
        
        # Get all active skills that have a github_path (synced from GitHub)
        synced_skills = Skill.objects.filter(is_active=True).exclude(github_path='')
        
        for skill in synced_skills:
            # Extract directory from github_path (e.g., "skills/code-review/SKILL.md" -> "skills/code-review")
            if not skill.github_path:
                continue
            skill_dir = '/'.join(skill.github_path.split('/')[:-1])
            
            should_prune = False
            reason = ""
            
            # Case 1: Directory no longer exists in GitHub
            if skill_dir not in github_dirs:
                should_prune = True
                reason = f"directory '{skill_dir}' no longer exists in GitHub"
            
            # Case 2: Directory maps to a different skill (duplicate)
            elif skill_dir in dir_to_skill_id and dir_to_skill_id[skill_dir] != skill.id:
                should_prune = True
                reason = f"directory '{skill_dir}' now belongs to skill ID {dir_to_skill_id[skill_dir]}"
            
            if should_prune:
                skill.is_active = False
                skill.save(update_fields=['is_active'])
                pruned.append(skill.name)
                logger.info(f"Pruned skill '{skill.name}' (ID: {skill.id}): {reason}")
        
        return pruned

    def _push_to_github(self):
        """Push database skills to GitHub.

        Pushes active skills that are newer than the GitHub version.
        Compares local updated_at with GitHub's last commit timestamp.
        Hidden skills are marked with 'hidden: true' in the SKILL.md frontmatter.
        """
        pushed = []
        skipped = []

        repo, branch = self._get_github_client_and_repo()

        # Get all active skills (including hidden ones) to preserve them in GitHub
        # Hidden skills will have 'hidden: true' in their SKILL.md frontmatter
        skills_to_push = Skill.objects.filter(is_active=True)

        for skill in skills_to_push:
            try:
                # Determine the GitHub path for this skill
                skill_dir_name = skill.name.lower().replace(' ', '-').replace('_', '-')
                skill_md_path = f"skills/{skill_dir_name}/SKILL.md"

                # Get GitHub file's last commit timestamp
                github_timestamp = self._get_github_file_timestamp(repo, skill_md_path, branch)

                # Only push if local version is newer than GitHub version
                # (or if skill doesn't exist in GitHub yet)
                should_push = True
                if github_timestamp and skill.updated_at:
                    if skill.updated_at <= github_timestamp:
                        logger.info(
                            f"Skipping push for '{skill.name}': GitHub version is newer or same "
                            f"(local: {skill.updated_at}, GitHub: {github_timestamp})"
                        )
                        should_push = False
                        skipped.append(skill.name)

                if should_push:
                    self.push_skill_to_github(skill)
                    pushed.append(skill.name)
            except SkillPushError as e:
                logger.warning(f"Failed to push skill {skill.name}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error pushing skill {skill.name}: {e}")

        logger.info(f"Pushed {len(pushed)} skills to GitHub, skipped {len(skipped)} (GitHub newer)")
        return pushed

    def sync_from_github(self):
        """
        Sync all skills from the configured GitHub repository.

        Looks for SKILL.md files in the 'skills/' directory of the repo.
        Each subdirectory should contain a SKILL.md file.

        Returns:
            List of synced Skill objects

        Raises:
            SkillSyncError: If sync fails
        """
        if not self.settings.skills_repo_url:
            raise SkillSyncError("No skills repository URL configured")

        # Initialize GitHub client
        token = self.settings.skills_repo_token or None
        github = Github(token)

        # Parse repo from URL
        url = self.settings.skills_repo_url.rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]

        parts = url.split('/')
        if len(parts) < 2:
            raise SkillSyncError(f"Invalid repository URL: {self.settings.skills_repo_url}")

        owner, repo_name = parts[-2], parts[-1]

        try:
            repo = github.get_repo(f"{owner}/{repo_name}")
        except GithubException as e:
            raise SkillSyncError(f"Cannot access repository: {e.data.get('message', str(e))}")

        # Get contents of skills directory
        branch = self.settings.skills_repo_branch or 'main'
        try:
            contents = repo.get_contents("skills", ref=branch)
        except GithubException as e:
            raise SkillSyncError(f"Cannot find 'skills' directory: {e.data.get('message', str(e))}")

        synced = []
        errors = []

        for item in contents:
            if item.type == "dir":
                try:
                    skill = self._process_skill_dir(repo, item.path, branch)
                    if skill:
                        synced.append(skill)
                except Exception as e:
                    errors.append(f"{item.path}: {str(e)}")
                    logger.warning(f"Failed to sync skill from {item.path}: {e}")

        if errors and not synced:
            raise SkillSyncError(f"All skills failed to sync: {'; '.join(errors)}")

        logger.info(f"Synced {len(synced)} skills from {owner}/{repo_name}")
        return synced

    def _process_skill_dir(self, repo, dir_path, branch):
        """
        Process a single skill directory.

        Compares timestamps to determine if GitHub version should overwrite local:
        - If skill doesn't exist locally: create from GitHub
        - If GitHub version is newer than local updated_at: update from GitHub
        - If local version is newer: skip update (will be pushed in push phase)

        Args:
            repo: PyGithub Repository object
            dir_path: Path to skill directory (e.g., 'skills/code-review')
            branch: Branch name

        Returns:
            Skill object or None
        """
        skill_md_path = f"{dir_path}/SKILL.md"

        try:
            file_content = repo.get_contents(skill_md_path, ref=branch)
            content = file_content.decoded_content.decode('utf-8')
        except GithubException:
            logger.debug(f"No SKILL.md found in {dir_path}")
            return None

        # Parse the SKILL.md
        skill_data = self.parse_skill_md(content)
        self._validate_skill_data(skill_data)

        # Check if skill already exists locally
        existing_skill = Skill.objects.filter(name=skill_data['name']).first()

        # Get GitHub file's last commit timestamp
        github_timestamp = self._get_github_file_timestamp(repo, skill_md_path, branch)

        # Determine if we should update from GitHub based on timestamps
        should_update_from_github = True
        if existing_skill and github_timestamp:
            local_timestamp = existing_skill.updated_at
            # Compare timestamps - only update if GitHub is newer
            if local_timestamp and local_timestamp > github_timestamp:
                logger.info(
                    f"Skipping pull for '{skill_data['name']}': local version is newer "
                    f"(local: {local_timestamp}, GitHub: {github_timestamp})"
                )
                should_update_from_github = False

        if not should_update_from_github:
            # Return existing skill without updating - it will be pushed in push phase
            return existing_skill

        # Check for context files in the directory
        context_files = {}
        try:
            dir_contents = repo.get_contents(dir_path, ref=branch)
            for item in dir_contents:
                if item.type == "file" and item.name != "SKILL.md":
                    try:
                        file_content = repo.get_contents(item.path, ref=branch)
                        context_files[item.name] = file_content.decoded_content.decode('utf-8')
                    except Exception:
                        pass  # Skip files that can't be read
        except GithubException:
            pass  # No additional files

        # Create or update skill from GitHub
        # Respect the hidden flag from GitHub - this allows restoring deleted skills
        # by changing hidden: true to hidden: false in the SKILL.md file
        skill, created = Skill.objects.update_or_create(
            name=skill_data['name'],
            defaults={
                'description': skill_data['description'],
                'instructions': skill_data['instructions'],
                'allowed_tools': skill_data['allowed_tools'],
                'tags': skill_data['tags'],
                'context_files': context_files,
                'github_path': skill_md_path,
                'last_synced': timezone.now(),
                'is_active': True,
                'is_hidden': skill_data.get('hidden', False),
                'is_curated': skill_data.get('curated', False),
            }
        )

        # Clear deleted_at if skill was restored (hidden changed from True to False)
        if not skill_data.get('hidden', False) and skill.deleted_at:
            skill.deleted_at = None
            skill.deleted_by = None
            skill.save(update_fields=['deleted_at', 'deleted_by'])
            logger.info(f"Restored previously deleted skill: {skill.name}")

        action = "Created" if created else "Updated from GitHub"
        logger.info(f"{action} skill: {skill.name}")

        return skill

    def get_skill_by_name(self, name, user=None):
        """
        Get a skill by its exact name.

        For personal skills, the user must be the owner.
        Global skills are accessible to all.

        Args:
            name: Skill name
            user: Optional User to include personal skills for

        Returns:
            Skill object or None
        """
        if user and user.is_authenticated:
            # Return skill if it's global OR if it's the user's personal skill
            return Skill.objects.filter(
                name=name,
                is_active=True
            ).filter(
                models.Q(scope='global') |
                models.Q(scope='personal', created_by=user)
            ).first()
        return Skill.objects.filter(name=name, is_active=True, scope='global').first()

    def list_skills(self, tags=None, curated_only=False, user=None):
        """
        List all active skills with optional filtering.

        When user is provided, returns global skills plus the user's personal skills.
        Personal skills from a user override global skills of the same name.

        Args:
            tags: Optional list of tags to filter by
            curated_only: If True, only return curated skills (global only)
            user: Optional User object to include personal skills for

        Returns:
            QuerySet of Skill objects
        """
        if user and user.is_authenticated:
            queryset = Skill.objects.filter(is_active=True).filter(
                models.Q(scope='global') |
                models.Q(scope='personal', created_by=user)
            )
        else:
            queryset = Skill.objects.filter(is_active=True, scope='global')

        if curated_only:
            queryset = queryset.filter(is_curated=True)

        if tags:
            for tag in tags:
                queryset = queryset.filter(tags__contains=tag)

        return queryset

    def search_skills(self, query, limit=5, user=None):
        """
        Search for skills by description (basic text search).

        When user is provided, includes the user's personal skills in results.

        Args:
            query: Search query string
            limit: Maximum number of results
            user: Optional User object to include personal skills for

        Returns:
            List of Skill objects
        """
        if user and user.is_authenticated:
            base_filter = models.Q(is_active=True) & (
                models.Q(scope='global') |
                models.Q(scope='personal', created_by=user)
            )
        else:
            base_filter = models.Q(is_active=True, scope='global')

        skills = Skill.objects.filter(base_filter).filter(
            models.Q(name__icontains=query) |
            models.Q(description__icontains=query) |
            models.Q(tags__icontains=query)
        )[:limit]

        return list(skills)

    @staticmethod
    def _parse_repo_url(repo_url):
        """
        Parse a GitHub URL into (owner, repo_name).

        Handles trailing slashes, .git suffix, and various URL formats.

        Args:
            repo_url: Full GitHub URL (e.g., 'https://github.com/org/repo')

        Returns:
            Tuple of (owner, repo_name)

        Raises:
            SkillSyncError: If URL is invalid
        """
        url = repo_url.strip().rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
        parts = url.split('/')
        if len(parts) < 2:
            raise SkillSyncError(f"Invalid repository URL: {repo_url}")
        return parts[-2], parts[-1]

    def list_skills_from_external_repo(self, repo_url, branch='main', token=None):
        """
        Discover available skills in an external GitHub repository without importing.

        Scans the 'skills/' directory for subdirectories containing SKILL.md files,
        parses their metadata, and returns a list of available skills.

        Args:
            repo_url: Full GitHub URL (e.g., 'https://github.com/org/community-skills')
            branch: Branch to scan (default: 'main')
            token: Optional GitHub token for private repos

        Returns:
            List of dicts: [{'name': str, 'description': str, 'tags': list, 'path': str}, ...]

        Raises:
            SkillSyncError: If repo is inaccessible or has no skills directory
        """
        owner, repo_name = self._parse_repo_url(repo_url)

        github = Github(token) if token else Github()
        try:
            repo = github.get_repo(f"{owner}/{repo_name}")
        except GithubException as e:
            raise SkillSyncError(f"Cannot access repository: {e.data.get('message', str(e))}")

        try:
            contents = repo.get_contents("skills", ref=branch)
        except GithubException as e:
            if e.status == 404:
                raise SkillSyncError("No 'skills' directory found in this repository")
            raise SkillSyncError(f"Cannot access 'skills' directory: {e.data.get('message', str(e))}")

        available = []
        for item in contents:
            if item.type != "dir":
                continue
            skill_md_path = f"{item.path}/SKILL.md"
            try:
                file_content = repo.get_contents(skill_md_path, ref=branch)
                content = file_content.decoded_content.decode('utf-8')
                skill_data = self.parse_skill_md(content)
                available.append({
                    'name': skill_data['name'],
                    'description': skill_data.get('description', ''),
                    'tags': skill_data.get('tags', []),
                    'path': item.path,
                })
            except GithubException:
                logger.debug(f"No SKILL.md found in {item.path}")
            except (ValueError, KeyError) as e:
                logger.debug(f"Invalid SKILL.md in {item.path}: {e}")

        return available

    def import_skills_from_external_repo(self, repo_url, skill_names, branch='main',
                                         token=None, user=None, scope='personal'):
        """
        Import selected skills from an external GitHub repository into the database.

        Args:
            repo_url: Full GitHub URL
            skill_names: List of skill names to import (as returned by list_skills_from_external_repo)
            branch: Branch name (default: 'main')
            token: Optional GitHub token for private repos
            user: Django User performing the import
            scope: 'global' or 'personal'

        Returns:
            Dict: {'imported': [names], 'skipped': [names], 'errors': [messages]}
        """
        owner, repo_name = self._parse_repo_url(repo_url)
        skill_names_set = set(skill_names)

        github = Github(token) if token else Github()
        try:
            repo = github.get_repo(f"{owner}/{repo_name}")
        except GithubException as e:
            raise SkillSyncError(f"Cannot access repository: {e.data.get('message', str(e))}")

        try:
            contents = repo.get_contents("skills", ref=branch)
        except GithubException as e:
            if e.status == 404:
                raise SkillSyncError("No 'skills' directory found in this repository")
            raise SkillSyncError(f"Cannot access 'skills' directory: {e.data.get('message', str(e))}")

        imported = []
        skipped = []
        errors = []

        for item in contents:
            if item.type != "dir":
                continue

            skill_md_path = f"{item.path}/SKILL.md"
            try:
                file_content = repo.get_contents(skill_md_path, ref=branch)
                content = file_content.decoded_content.decode('utf-8')
                skill_data = self.parse_skill_md(content)
                self._validate_skill_data(skill_data)
            except GithubException:
                continue
            except (ValueError, KeyError) as e:
                errors.append(f"{item.path}: {str(e)}")
                continue

            if skill_data['name'] not in skill_names_set:
                continue

            # Fetch context files
            context_files = {}
            try:
                dir_contents = repo.get_contents(item.path, ref=branch)
                for f in dir_contents:
                    if f.type == "file" and f.name != "SKILL.md":
                        try:
                            fc = repo.get_contents(f.path, ref=branch)
                            context_files[f.name] = fc.decoded_content.decode('utf-8')
                        except Exception:
                            pass
            except GithubException:
                pass

            # Create or update skill
            try:
                lookup = {'name': skill_data['name']}
                if scope == 'personal':
                    lookup['scope'] = 'personal'
                    lookup['created_by'] = user
                else:
                    lookup['scope'] = 'global'

                skill, created = Skill.objects.update_or_create(
                    **lookup,
                    defaults={
                        'description': skill_data['description'],
                        'instructions': skill_data['instructions'],
                        'allowed_tools': skill_data.get('allowed_tools', []),
                        'tags': skill_data.get('tags', []),
                        'context_files': context_files,
                        'scope': scope,
                        'source_repo_url': repo_url,
                        'last_synced': timezone.now(),
                        'created_by': user,
                        'is_active': True,
                    }
                )
                imported.append(skill_data['name'])
                logger.info(f"Imported skill '{skill_data['name']}' from {repo_url} ({scope})")
            except Exception as e:
                errors.append(f"{skill_data['name']}: {str(e)}")
                logger.warning(f"Failed to import skill '{skill_data['name']}': {e}")

        # Track skills that were requested but not found
        for name in skill_names_set - set(imported) - {e.split(':')[0] for e in errors}:
            skipped.append(name)

        return {'imported': imported, 'skipped': skipped, 'errors': errors}

    def sync_user_skills(self, user):
        """
        Sync personal skills for a specific user from their configured GitHub repo.

        Fetches skills from the user's skills_repo_url (set in UserGitHubSettings)
        and creates/updates Skill objects with scope='personal' and created_by=user.

        Args:
            user: Django User object with github_settings configured

        Returns:
            Dict with sync results: {'synced': [...], 'errors': [...]}

        Raises:
            SkillSyncError: If user has no skills repo configured or sync fails
        """
        try:
            github_settings = user.github_settings
        except Exception:
            raise SkillSyncError("No GitHub settings configured for this user")

        if not github_settings.skills_repo_url:
            raise SkillSyncError("No personal skills repository URL configured. Set it in your profile settings.")

        if not github_settings.github_token:
            raise SkillSyncError("GitHub token required. Configure it in your profile settings.")

        token = github_settings.github_token
        repo_url = github_settings.skills_repo_url.rstrip('/')
        branch = github_settings.skills_repo_branch or 'main'

        if repo_url.endswith('.git'):
            repo_url = repo_url[:-4]

        parts = repo_url.split('/')
        if len(parts) < 2:
            raise SkillSyncError(f"Invalid personal skills repository URL: {repo_url}")

        owner, repo_name = parts[-2], parts[-1]

        github = Github(token)
        try:
            repo = github.get_repo(f"{owner}/{repo_name}")
        except GithubException as e:
            raise SkillSyncError(f"Cannot access personal skills repository: {e.data.get('message', str(e))}")

        try:
            contents = repo.get_contents("skills", ref=branch)
        except GithubException as e:
            if e.status == 404:
                logger.info(f"No 'skills' directory in user {user.username}'s repo yet")
                return {'synced': [], 'errors': []}
            raise SkillSyncError(f"Cannot access 'skills' directory: {e.data.get('message', str(e))}")

        synced = []
        errors = []
        synced_dirs = set()

        for item in contents:
            if item.type == "dir":
                synced_dirs.add(item.path)
                skill_md_path = f"{item.path}/SKILL.md"
                try:
                    file_content = repo.get_contents(skill_md_path, ref=branch)
                    content = file_content.decoded_content.decode('utf-8')
                    skill_data = self.parse_skill_md(content)
                    self._validate_skill_data(skill_data)

                    # Use name-user combination to allow personal skills with same name as global
                    # Personal skills get a unique lookup key: name + created_by
                    personal_name = skill_data['name']

                    skill, created = Skill.objects.update_or_create(
                        name=personal_name,
                        scope='personal',
                        created_by=user,
                        defaults={
                            'description': skill_data['description'],
                            'instructions': skill_data['instructions'],
                            'allowed_tools': skill_data.get('allowed_tools', []),
                            'tags': skill_data.get('tags', []),
                            'github_path': skill_md_path,
                            'source_repo_url': github_settings.skills_repo_url,
                            'last_synced': timezone.now(),
                            'is_active': True,
                            'is_hidden': skill_data.get('hidden', False),
                        }
                    )
                    synced.append(skill.name)
                    action = "Created" if created else "Updated"
                    logger.info(f"{action} personal skill '{skill.name}' for user {user.username}")
                except GithubException:
                    logger.debug(f"No SKILL.md found in {item.path}")
                except Exception as e:
                    errors.append(f"{item.path}: {str(e)}")
                    logger.warning(f"Failed to sync personal skill from {item.path}: {e}")

        # Deactivate personal skills whose directories no longer exist in the repo
        user_personal_skills = Skill.objects.filter(
            scope='personal',
            created_by=user,
            is_active=True
        ).exclude(github_path='')

        for skill in user_personal_skills:
            if not skill.github_path:
                continue
            skill_dir = '/'.join(skill.github_path.split('/')[:-1])
            if skill_dir not in synced_dirs:
                skill.is_active = False
                skill.save(update_fields=['is_active'])
                logger.info(f"Deactivated orphaned personal skill '{skill.name}' for user {user.username}")

        logger.info(f"Synced {len(synced)} personal skills for user {user.username}")
        return {'synced': synced, 'errors': errors}


# Import models at module level for search_skills Q objects
from django.db import models

"""
Management command to check and update status for running indexing jobs.

This command polls the Kubernetes API to check the status of running indexer jobs
and updates the corresponding PathfinderProject records. It's designed to be run
periodically (e.g., every 5 minutes) via a Kubernetes CronJob.
"""
from django.core.management.base import BaseCommand
from projects.models import PathfinderProject
from projects.utils import check_and_update_project_status
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check and update status for all running indexing jobs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Print detailed output for each project',
        )

    def handle(self, *args, **options):
        verbose = options.get('verbose', False)
        
        # Find all projects in "running" or "watching" status
        running_projects = PathfinderProject.objects.filter(status__in=['running', 'watching'])
        
        if running_projects.count() == 0:
            self.stdout.write(self.style.SUCCESS('No running or watching projects found.'))
            return
        
        self.stdout.write(f'Checking status for {running_projects.count()} active project(s)...')
        
        updated_count = 0
        failed_count = 0
        
        for project in running_projects:
            old_status = project.status
            
            try:
                # Check and update status (this function queries Kubernetes)
                check_and_update_project_status(project)
                
                # Refresh from database to get updated status
                project.refresh_from_db()
                new_status = project.status
                
                if old_status != new_status:
                    updated_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ {project.name} (ID:{project.id}): {old_status} → {new_status}'
                        )
                    )
                elif verbose:
                    self.stdout.write(
                        f'  {project.name} (ID:{project.id}): {old_status} (no change)'
                    )
                    
            except Exception as e:
                failed_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'✗ {project.name} (ID:{project.id}): Failed to check status - {str(e)}'
                    )
                )
                logger.error(f'Failed to check job status for project {project.id}: {e}')
        
        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Summary:'))
        self.stdout.write(f'  Total checked: {running_projects.count()}')
        self.stdout.write(f'  Status updated: {updated_count}')
        if failed_count > 0:
            self.stdout.write(self.style.WARNING(f'  Failed checks: {failed_count}'))
        self.stdout.write('')

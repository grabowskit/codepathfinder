"""
Management command to audit PathfinderProject records and Elasticsearch indices.
Phase 0 of MCP Project Scoping Implementation.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from projects.models import PathfinderProject
from elasticsearch import Elasticsearch
from django.conf import settings
import json
import os


class Command(BaseCommand):
    help = 'Audit PathfinderProject records and Elasticsearch index usage for Phase 0'

    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            type=str,
            default='text',
            choices=['text', 'json'],
            help='Output format (text or json)',
        )

    def handle(self, *args, **options):
        output_format = options['format']

        # Initialize Elasticsearch client (using same method as mcp_server/tools.py)
        es = None
        es_available = False
        try:
            endpoint = os.environ.get('ELASTICSEARCH_ENDPOINT')
            api_key = os.environ.get('ELASTICSEARCH_API_KEY')

            if endpoint and api_key:
                es = Elasticsearch(endpoint, api_key=api_key)
                es_available = es.ping()
            else:
                self.stdout.write(self.style.WARNING("Elasticsearch credentials not configured (ELASTICSEARCH_ENDPOINT or ELASTICSEARCH_API_KEY missing)"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Elasticsearch not available: {e}"))

        # Collect audit data
        audit_data = self._collect_audit_data(es, es_available)

        # Output results
        if output_format == 'json':
            self.stdout.write(json.dumps(audit_data, indent=2, default=str))
        else:
            self._print_text_report(audit_data)

    def _collect_audit_data(self, es, es_available):
        """Collect all audit data into a structured dictionary"""

        # 1. PathfinderProject Statistics
        total_projects = PathfinderProject.objects.count()
        projects_with_custom_index = PathfinderProject.objects.filter(
            custom_index_name__isnull=False
        ).exclude(custom_index_name='').count()
        projects_without_custom_index = total_projects - projects_with_custom_index

        # 2. Check for duplicate custom_index_name values
        duplicates = PathfinderProject.objects.values('custom_index_name').annotate(
            count=Count('id')
        ).filter(count__gt=1, custom_index_name__isnull=False).exclude(custom_index_name='')

        duplicate_indices = []
        for dup in duplicates:
            projects = PathfinderProject.objects.filter(
                custom_index_name=dup['custom_index_name']
            ).values('id', 'name', 'user__username')
            duplicate_indices.append({
                'index_name': dup['custom_index_name'],
                'count': dup['count'],
                'projects': list(projects)
            })

        # 3. Projects without custom_index_name
        projects_needing_migration = []
        for project in PathfinderProject.objects.filter(
            Q(custom_index_name__isnull=True) | Q(custom_index_name='')
        ).values('id', 'name', 'user__username', 'repository_url', 'status'):
            projects_needing_migration.append(project)

        # 4. Elasticsearch index analysis
        es_indices = []
        es_index_stats = {}
        if es_available:
            try:
                # Get all indices
                all_indices = es.indices.get_alias(index="*")

                # Filter for potential code indices
                for index_name in all_indices.keys():
                    if not index_name.startswith('.'):  # Skip system indices
                        stats = es.indices.stats(index=index_name)
                        doc_count = stats['indices'][index_name]['total']['docs']['count']
                        size_bytes = stats['indices'][index_name]['total']['store']['size_in_bytes']

                        es_indices.append({
                            'name': index_name,
                            'doc_count': doc_count,
                            'size_mb': round(size_bytes / 1024 / 1024, 2)
                        })

                # Check which indices match project names
                project_index_names = set(
                    PathfinderProject.objects.filter(
                        custom_index_name__isnull=False
                    ).exclude(custom_index_name='').values_list('custom_index_name', flat=True)
                )

                matched_indices = [idx for idx in es_indices if idx['name'] in project_index_names]
                unmatched_indices = [idx for idx in es_indices if idx['name'] not in project_index_names]

                es_index_stats = {
                    'total_indices': len(es_indices),
                    'matched_to_projects': len(matched_indices),
                    'unmatched': len(unmatched_indices),
                    'matched_indices': matched_indices,
                    'unmatched_indices': unmatched_indices
                }
            except Exception as e:
                es_index_stats['error'] = str(e)

        # 5. Recommendations
        recommendations = []

        if projects_without_custom_index > 0:
            recommendations.append({
                'priority': 'HIGH',
                'issue': f'{projects_without_custom_index} projects lack custom_index_name',
                'action': 'Run data migration to assign project-{id} format'
            })

        if duplicate_indices:
            recommendations.append({
                'priority': 'CRITICAL',
                'issue': f'{len(duplicate_indices)} duplicate index names found',
                'action': 'Manually resolve conflicts before proceeding'
            })

        if es_available and es_index_stats.get('unmatched'):
            recommendations.append({
                'priority': 'MEDIUM',
                'issue': f'{len(es_index_stats["unmatched_indices"])} ES indices not linked to projects',
                'action': 'Review orphaned indices - may be legacy data'
            })

        if not es_available:
            recommendations.append({
                'priority': 'HIGH',
                'issue': 'Elasticsearch not available',
                'action': 'Ensure ES is running before proceeding with migration'
            })

        return {
            'summary': {
                'total_projects': total_projects,
                'projects_with_custom_index': projects_with_custom_index,
                'projects_without_custom_index': projects_without_custom_index,
                'duplicate_index_count': len(duplicate_indices),
                'elasticsearch_available': es_available
            },
            'duplicate_indices': duplicate_indices,
            'projects_needing_migration': projects_needing_migration,
            'elasticsearch_indices': es_index_stats,
            'recommendations': recommendations
        }

    def _print_text_report(self, data):
        """Print a formatted text report"""

        self.stdout.write(self.style.SUCCESS('\n' + '='*80))
        self.stdout.write(self.style.SUCCESS('  PHASE 0: PathfinderProject & Elasticsearch Index Audit'))
        self.stdout.write(self.style.SUCCESS('='*80 + '\n'))

        # Summary
        self.stdout.write(self.style.HTTP_INFO('SUMMARY'))
        self.stdout.write(f"  Total Projects:               {data['summary']['total_projects']}")
        self.stdout.write(f"  Projects with custom_index:   {data['summary']['projects_with_custom_index']}")
        self.stdout.write(f"  Projects WITHOUT index name:  {data['summary']['projects_without_custom_index']}")
        self.stdout.write(f"  Duplicate index names:        {data['summary']['duplicate_index_count']}")
        self.stdout.write(f"  Elasticsearch available:      {data['summary']['elasticsearch_available']}\n")

        # Duplicates
        if data['duplicate_indices']:
            self.stdout.write(self.style.ERROR('DUPLICATE INDEX NAMES (CRITICAL)'))
            for dup in data['duplicate_indices']:
                self.stdout.write(f"  Index: {dup['index_name']} (used by {dup['count']} projects)")
                for proj in dup['projects']:
                    self.stdout.write(f"    - Project ID {proj['id']}: {proj['name']} (owner: {proj['user__username']})")
            self.stdout.write('')

        # Projects needing migration
        if data['projects_needing_migration']:
            self.stdout.write(self.style.WARNING('PROJECTS NEEDING MIGRATION'))
            self.stdout.write(f"  Count: {len(data['projects_needing_migration'])}\n")
            for proj in data['projects_needing_migration'][:10]:  # Show first 10
                self.stdout.write(f"  ID {proj['id']}: {proj['name']} (status: {proj['status']})")
                self.stdout.write(f"    Repo: {proj['repository_url']}")
            if len(data['projects_needing_migration']) > 10:
                self.stdout.write(f"  ... and {len(data['projects_needing_migration']) - 10} more\n")
            else:
                self.stdout.write('')

        # Elasticsearch indices
        if data['summary']['elasticsearch_available']:
            es_stats = data['elasticsearch_indices']
            self.stdout.write(self.style.HTTP_INFO('ELASTICSEARCH INDICES'))
            self.stdout.write(f"  Total indices:       {es_stats.get('total_indices', 0)}")
            self.stdout.write(f"  Matched to projects: {es_stats.get('matched_to_projects', 0)}")
            self.stdout.write(f"  Unmatched/orphaned:  {es_stats.get('unmatched', 0)}\n")

            if es_stats.get('matched_indices'):
                self.stdout.write('  Matched Indices:')
                for idx in es_stats['matched_indices'][:5]:
                    self.stdout.write(f"    - {idx['name']}: {idx['doc_count']} docs, {idx['size_mb']} MB")
                if len(es_stats['matched_indices']) > 5:
                    self.stdout.write(f"    ... and {len(es_stats['matched_indices']) - 5} more\n")
                else:
                    self.stdout.write('')

            if es_stats.get('unmatched_indices'):
                self.stdout.write('  Unmatched/Orphaned Indices:')
                for idx in es_stats['unmatched_indices'][:5]:
                    self.stdout.write(f"    - {idx['name']}: {idx['doc_count']} docs, {idx['size_mb']} MB")
                if len(es_stats['unmatched_indices']) > 5:
                    self.stdout.write(f"    ... and {len(es_stats['unmatched_indices']) - 5} more\n")
                else:
                    self.stdout.write('')

        # Recommendations
        self.stdout.write(self.style.SUCCESS('RECOMMENDATIONS'))
        for rec in data['recommendations']:
            priority_style = {
                'CRITICAL': self.style.ERROR,
                'HIGH': self.style.WARNING,
                'MEDIUM': self.style.NOTICE
            }.get(rec['priority'], self.style.NOTICE)

            self.stdout.write(priority_style(f"  [{rec['priority']}] {rec['issue']}"))
            self.stdout.write(f"    → {rec['action']}\n")

        self.stdout.write(self.style.SUCCESS('='*80))
        self.stdout.write(self.style.SUCCESS('  End of Audit Report'))
        self.stdout.write(self.style.SUCCESS('='*80 + '\n'))

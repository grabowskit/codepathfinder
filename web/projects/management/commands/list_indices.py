"""
Django management command to list all Elasticsearch indices with document counts.

Lists all non-system indices in the configured Elasticsearch cluster,
showing index name, document count, and storage size.

Usage:
    python manage.py list_indices
    python manage.py list_indices --format json
    python manage.py list_indices --sort size
    python manage.py list_indices --filter project-
"""
from django.core.management.base import BaseCommand
from projects.utils import get_es_client
import json


class Command(BaseCommand):
    help = 'List all Elasticsearch indices with document counts and sizes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            type=str,
            default='text',
            choices=['text', 'json'],
            help='Output format (text or json)',
        )
        parser.add_argument(
            '--sort',
            type=str,
            default='name',
            choices=['name', 'docs', 'size'],
            help='Sort indices by: name (alphabetical), docs (document count), size (storage size)',
        )
        parser.add_argument(
            '--filter',
            type=str,
            default=None,
            help='Filter indices by prefix (e.g., --filter project-)',
        )
        parser.add_argument(
            '--include-system',
            action='store_true',
            help='Include Elasticsearch system indices (starting with .)',
        )

    def handle(self, *args, **options):
        output_format = options['format']
        sort_by = options['sort']
        filter_prefix = options['filter']
        include_system = options['include_system']

        # Get Elasticsearch client using existing utility
        es = get_es_client()

        if es is None:
            self._handle_no_client(output_format)
            return

        # Check connection
        try:
            if not es.ping():
                self._handle_connection_error("Elasticsearch ping failed", output_format)
                return
        except Exception as e:
            self._handle_connection_error(str(e), output_format)
            return

        # Collect index data
        try:
            indices = self._collect_indices(es, filter_prefix, include_system)
        except Exception as e:
            self._handle_error(f"Failed to retrieve indices: {e}", output_format)
            return

        # Sort indices
        indices = self._sort_indices(indices, sort_by)

        # Output results
        if output_format == 'json':
            self._output_json(indices)
        else:
            self._output_text(indices)

    def _collect_indices(self, es, filter_prefix, include_system):
        """Collect index information from Elasticsearch."""
        indices = []

        # Get all indices
        all_indices = es.indices.get_alias(index="*")

        for index_name in all_indices.keys():
            # Skip system indices unless requested
            if not include_system and index_name.startswith('.'):
                continue

            # Apply filter if specified
            if filter_prefix and not index_name.startswith(filter_prefix):
                continue

            # Get stats for this index
            stats = es.indices.stats(index=index_name)
            doc_count = stats['indices'][index_name]['total']['docs']['count']
            size_bytes = stats['indices'][index_name]['total']['store']['size_in_bytes']

            indices.append({
                'name': index_name,
                'doc_count': doc_count,
                'size_bytes': size_bytes,
                'size_mb': round(size_bytes / 1024 / 1024, 2),
            })

        return indices

    def _sort_indices(self, indices, sort_by):
        """Sort indices by the specified field."""
        sort_key_map = {
            'name': lambda x: x['name'],
            'docs': lambda x: x['doc_count'],
            'size': lambda x: x['size_bytes'],
        }
        reverse = sort_by in ('docs', 'size')  # Descending for numeric fields
        return sorted(indices, key=sort_key_map[sort_by], reverse=reverse)

    def _handle_no_client(self, output_format):
        """Handle case where ES client cannot be created."""
        error_msg = "Elasticsearch not configured. Check SystemSettings in admin."
        if output_format == 'json':
            self.stdout.write(json.dumps({
                'success': False,
                'error': error_msg,
                'indices': []
            }, indent=2))
        else:
            self.stdout.write(self.style.ERROR(f"ERROR: {error_msg}"))
            self.stdout.write(self.style.WARNING(
                "Configure Elasticsearch via: Settings > System Settings"
            ))

    def _handle_connection_error(self, message, output_format):
        """Handle Elasticsearch connection errors."""
        if output_format == 'json':
            self.stdout.write(json.dumps({
                'success': False,
                'error': f"Connection failed: {message}",
                'indices': []
            }, indent=2))
        else:
            self.stdout.write(self.style.ERROR("ERROR: Cannot connect to Elasticsearch"))
            self.stdout.write(self.style.WARNING(f"  Details: {message}"))

    def _handle_error(self, message, output_format):
        """Handle general errors."""
        if output_format == 'json':
            self.stdout.write(json.dumps({
                'success': False,
                'error': message,
                'indices': []
            }, indent=2))
        else:
            self.stdout.write(self.style.ERROR(f"ERROR: {message}"))

    def _output_json(self, indices):
        """Output indices as JSON."""
        total_docs = sum(idx['doc_count'] for idx in indices)
        total_size_mb = sum(idx['size_mb'] for idx in indices)

        output = {
            'success': True,
            'summary': {
                'total_indices': len(indices),
                'total_documents': total_docs,
                'total_size_mb': round(total_size_mb, 2),
            },
            'indices': indices
        }
        self.stdout.write(json.dumps(output, indent=2))

    def _output_text(self, indices):
        """Output indices as formatted text table."""
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('Elasticsearch Indices'))
        self.stdout.write(self.style.HTTP_INFO('=' * 70))

        if not indices:
            self.stdout.write(self.style.WARNING('  No indices found.'))
            return

        # Header
        self.stdout.write(f"  {'Index Name':<40} {'Documents':>12} {'Size (MB)':>12}")
        self.stdout.write(f"  {'-' * 40} {'-' * 12} {'-' * 12}")

        # Rows
        total_docs = 0
        total_size_mb = 0

        for idx in indices:
            total_docs += idx['doc_count']
            total_size_mb += idx['size_mb']
            self.stdout.write(
                f"  {idx['name']:<40} {idx['doc_count']:>12,} {idx['size_mb']:>12.2f}"
            )

        # Footer
        self.stdout.write(f"  {'-' * 40} {'-' * 12} {'-' * 12}")
        self.stdout.write(
            f"  {'TOTAL':<40} {total_docs:>12,} {total_size_mb:>12.2f}"
        )
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'  Found {len(indices)} indices.'))
        self.stdout.write('')

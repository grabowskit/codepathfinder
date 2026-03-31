"""
Management command: create_memories_index

Creates (or updates) the Elasticsearch index for Memories with:
  - Standard text fields: title, content
  - semantic_text field for ELSER-based semantic search: content_semantic
  - keyword fields: tags, scope, memory_type
  - integer fields: memory_id, user_id, chunk_index

Run once after deploy (idempotent — create-or-update):
  python manage.py create_memories_index
"""

from django.core.management.base import BaseCommand, CommandError
from projects.utils import get_es_client


_MEMORIES_INDEX_BODY = {
    "mappings": {
        "properties": {
            "memory_id": {"type": "integer"},
            "title": {"type": "text"},
            "content": {"type": "text"},
            "content_semantic": {
                "type": "semantic_text",
                # inference_id is filled in at runtime from SystemSettings
            },
            "tags": {"type": "keyword"},
            "scope": {"type": "keyword"},
            "memory_type": {"type": "keyword"},
            "user_id": {"type": "integer"},
            "chunk_index": {"type": "integer"},
            "created_at": {"type": "date"},
        }
    }
}


class Command(BaseCommand):
    help = "Create or update the Elasticsearch 'memories' index"

    def add_arguments(self, parser):
        parser.add_argument(
            '--inference-id',
            default=None,
            help="Override ELSER inference endpoint ID (default: from SystemSettings)"
        )
        parser.add_argument(
            '--recreate',
            action='store_true',
            help="Delete and recreate the index (WARNING: destroys existing data)"
        )

    def handle(self, *args, **options):
        es = get_es_client()
        if not es:
            raise CommandError("Could not connect to Elasticsearch. Check SystemSettings.")

        inference_id = options.get('inference_id')
        if not inference_id:
            try:
                from core.models import SystemSettings
                s = SystemSettings.get_settings()
                inference_id = s.inference_id or '.elser-2-elasticsearch'
            except Exception:
                inference_id = '.elser-2-elasticsearch'

        self.stdout.write(f"Using inference endpoint: {inference_id}")

        index_body = dict(_MEMORIES_INDEX_BODY)
        # Inject inference_id into the semantic_text mapping
        index_body["mappings"]["properties"]["content_semantic"] = {
            "type": "semantic_text",
            "inference_id": inference_id,
        }

        index_name = 'memories'

        if options['recreate']:
            if es.indices.exists(index=index_name):
                self.stdout.write(f"Deleting existing index '{index_name}'...")
                es.indices.delete(index=index_name)
                self.stdout.write(self.style.WARNING(f"Deleted '{index_name}'"))

        if es.indices.exists(index=index_name):
            self.stdout.write(f"Index '{index_name}' already exists. Updating mappings...")
            try:
                es.indices.put_mapping(
                    index=index_name,
                    body=index_body["mappings"],
                )
                self.stdout.write(self.style.SUCCESS(f"Updated mappings for '{index_name}'"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Could not update mappings: {e}"))
        else:
            self.stdout.write(f"Creating index '{index_name}'...")
            try:
                es.indices.create(index=index_name, body=index_body)
                self.stdout.write(self.style.SUCCESS(f"Created index '{index_name}'"))
            except Exception as e:
                raise CommandError(f"Failed to create index: {e}")

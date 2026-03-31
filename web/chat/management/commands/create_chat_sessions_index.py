"""
Management command: create_chat_sessions_index

Creates (or updates) the Elasticsearch index 'panel_chat' used by the
Ask CodePathfinder side panel to persist chat sessions.

Two document types are stored in this single index (discriminated by 'type'):
  conv — conversation metadata (one per conversation)
  msg  — individual messages

Run once after deploy (idempotent — create-or-update):
  python manage.py create_chat_sessions_index
"""

from django.core.management.base import BaseCommand, CommandError
from projects.utils import get_es_client


_INDEX_BODY = {
    "mappings": {
        "properties": {
            "type":            {"type": "keyword"},
            "conversation_id": {"type": "keyword"},
            "user_id":         {"type": "integer"},
            "project_id":      {"type": "integer"},
            # conv fields
            "title":           {"type": "keyword"},
            "message_count":   {"type": "integer"},
            "created_at":      {"type": "date"},
            "updated_at":      {"type": "date"},
            # msg fields
            "role":            {"type": "keyword"},
            "content":         {"type": "text"},
            "message_index":   {"type": "integer"},
        }
    },
}

INDEX_NAME = "panel_chat"


class Command(BaseCommand):
    help = "Create or update the Elasticsearch 'panel_chat' index for side-panel chat sessions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--recreate",
            action="store_true",
            help="Delete and recreate the index (WARNING: destroys existing chat history)",
        )

    def handle(self, *args, **options):
        es = get_es_client()
        if not es:
            raise CommandError(
                "Could not connect to Elasticsearch. Check SystemSettings."
            )

        if options["recreate"]:
            if es.indices.exists(index=INDEX_NAME):
                self.stdout.write(f"Deleting existing index '{INDEX_NAME}'...")
                es.indices.delete(index=INDEX_NAME)
                self.stdout.write(self.style.WARNING(f"Deleted '{INDEX_NAME}'"))

        if es.indices.exists(index=INDEX_NAME):
            self.stdout.write(
                f"Index '{INDEX_NAME}' already exists — updating mappings..."
            )
            try:
                es.indices.put_mapping(
                    index=INDEX_NAME,
                    body=_INDEX_BODY["mappings"],
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Updated mappings for '{INDEX_NAME}'")
                )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"Could not update mappings: {e}")
                )
        else:
            self.stdout.write(f"Creating index '{INDEX_NAME}'...")
            try:
                es.indices.create(index=INDEX_NAME, body=_INDEX_BODY)
                self.stdout.write(self.style.SUCCESS(f"Created index '{INDEX_NAME}'"))
            except Exception as e:
                raise CommandError(f"Failed to create index: {e}")

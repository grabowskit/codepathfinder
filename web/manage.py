#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # Load .env file from project root if it exists
    # apps/web/manage.py -> apps/web -> apps -> pathfinder (root)
    # So we need to go up 2 levels
    try:
        from dotenv import load_dotenv
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        dotenv_path = os.path.join(base_dir, '.env')
        if os.path.exists(dotenv_path):
            load_dotenv(dotenv_path)
            # print(f"Loaded .env from {dotenv_path}")
    except ImportError:
        pass

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CodePathfinder.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # OTel is initialized in CoreConfig.ready() — after Django's logging
    # config has been applied, so our LoggingHandler isn't wiped by dictConfig.
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()

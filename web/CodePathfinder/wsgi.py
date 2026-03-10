"""
WSGI config for CodePathfinder project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# Load .env file from project root if it exists
try:
    from dotenv import load_dotenv
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dotenv_path = os.path.join(base_dir, '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CodePathfinder.settings')

# OTel is initialized in CoreConfig.ready() — after Django's logging
# config has been applied, so our LoggingHandler isn't wiped by dictConfig.
application = get_wsgi_application()

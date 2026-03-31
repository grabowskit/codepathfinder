import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CodePathfinder.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

if not User.objects.filter(username='tom@grabowski.org').exists():
    User.objects.create_superuser('tom@grabowski.org', 'tom@grabowski.org', 'Code2Context')
    print("Superuser created.")
else:
    print("Superuser already exists.")

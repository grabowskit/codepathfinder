#!/usr/bin/env python
"""
Script to set up Google OAuth in django-allauth
Run this with: docker-compose exec web python setup_google_oauth.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CodePathfinder.settings')
django.setup()

from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp

# Get credentials from environment
client_id = os.getenv('GOOGLE_CLIENT_ID')
client_secret = os.getenv('GOOGLE_CLIENT_SECRET')

if not client_id or not client_secret:
    print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in your .env file")
    print("Please add them to your .env file and restart the containers")
    exit(1)

# Get or create the site
site = Site.objects.get(pk=1)
print(f"Using site: {site.domain} (ID: {site.id})")

# Create or update Google SocialApp
social_app, created = SocialApp.objects.update_or_create(
    provider='google',
    defaults={
        'name': 'Google',
        'client_id': client_id,
        'secret': client_secret,
    }
)

# Add site to the social app
social_app.sites.add(site)

if created:
    print("✓ Google OAuth has been configured successfully!")
else:
    print("✓ Google OAuth configuration has been updated!")

print(f"  Client ID: {client_id[:20]}...")
print(f"  Provider: {social_app.provider}")
print(f"  Sites: {', '.join([s.domain for s in social_app.sites.all()])}")

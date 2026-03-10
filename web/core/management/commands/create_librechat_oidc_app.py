"""
Management command to create (or display) the OAuth2/OIDC Application for LibreChat.

DOT 2.3.0 hashes client_secret on save (ClientSecretField), so the raw secret must be
captured before .save() is called. This command generates the secret, prints it, then
saves — ensuring you always get the usable plaintext value.

Usage:
    python manage.py create_librechat_oidc_app
    python manage.py create_librechat_oidc_app --reset-secret
"""
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from oauth2_provider.models import Application
from oauth2_provider.generators import generate_client_id

User = get_user_model()

REDIRECT_URIS = "\n".join([
    "https://chat.codepathfinder.com/oauth/openid/callback",
    "https://localhost:3443/oauth/openid/callback",
    "http://localhost:3080/oauth/openid/callback",
])

POST_LOGOUT_REDIRECT_URIS = "\n".join([
    "https://codepathfinder.com",
    "https://localhost:8443",
])


class Command(BaseCommand):
    help = "Create (or display) the OAuth2/OIDC application for LibreChat SSO."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-secret",
            action="store_true",
            help="Regenerate the client secret for the existing LibreChat application.",
        )

    def handle(self, *args, **options):
        # Find a superuser to own the application (required by DOT)
        owner = User.objects.filter(is_superuser=True).order_by("id").first()
        if not owner:
            self.stderr.write(self.style.ERROR(
                "No superuser found. Create a superuser first: python manage.py createsuperuser"
            ))
            return

        raw_secret = None

        try:
            app = Application.objects.get(name="LibreChat")
            created = False
        except Application.DoesNotExist:
            created = True
            app = None

        if created:
            # Generate raw secret BEFORE saving so we can print it
            raw_secret = secrets.token_urlsafe(40)
            client_id = generate_client_id()
            app = Application(
                name="LibreChat",
                client_id=client_id,
                client_secret=raw_secret,  # will be hashed on save
                client_type=Application.CLIENT_CONFIDENTIAL,
                authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
                redirect_uris=REDIRECT_URIS,
                post_logout_redirect_uris=POST_LOGOUT_REDIRECT_URIS,
                skip_authorization=True,
                algorithm="RS256",
                user=owner,
            )
            app.save()
            self.stdout.write(self.style.SUCCESS("LibreChat OIDC application created."))

        elif options["reset_secret"]:
            raw_secret = secrets.token_urlsafe(40)
            app.client_secret = raw_secret  # will be hashed on save
            app.save()
            self.stdout.write(self.style.WARNING("Client secret regenerated."))

        else:
            self.stdout.write(
                "LibreChat OIDC application already exists.\n"
                "Use --reset-secret to rotate the client secret."
            )

        # Ensure redirect URIs and post-logout URIs are up-to-date on existing apps
        if not created:
            update_fields = []

            current_uris = set(app.redirect_uris.splitlines())
            desired_uris = set(REDIRECT_URIS.splitlines())
            if not desired_uris.issubset(current_uris):
                app.redirect_uris = "\n".join(current_uris | desired_uris)
                update_fields.append('redirect_uris')
                self.stdout.write("Redirect URIs updated.")

            current_logout_uris = set((app.post_logout_redirect_uris or "").splitlines())
            desired_logout_uris = set(POST_LOGOUT_REDIRECT_URIS.splitlines())
            if not desired_logout_uris.issubset(current_logout_uris):
                app.post_logout_redirect_uris = "\n".join(current_logout_uris | desired_logout_uris)
                update_fields.append('post_logout_redirect_uris')
                self.stdout.write("Post-logout redirect URIs updated.")

            if update_fields:
                # Use update_fields to avoid re-hashing the stored client_secret
                app.save(update_fields=update_fields)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("=== LibreChat OIDC Credentials ==="))
        self.stdout.write(f"  OPENID_CLIENT_ID     = {app.client_id}")

        if raw_secret:
            self.stdout.write(f"  OPENID_CLIENT_SECRET = {raw_secret}")
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "  ⚠  The secret above is the ONLY time it will be shown in plaintext."
            ))
        else:
            self.stdout.write("  OPENID_CLIENT_SECRET = <hashed — run --reset-secret to rotate>")

        self.stdout.write("")
        self.stdout.write("Add these to:")
        self.stdout.write("  - Local dev:    chat-config/.env  (OPENID_CLIENT_ID / OPENID_CLIENT_SECRET)")
        self.stdout.write("  - Production:   kubectl secret 'librechat-secrets' (OPENID_CLIENT_ID / OPENID_CLIENT_SECRET)")
        self.stdout.write("")
        self.stdout.write("Also set OIDC_RSA_PRIVATE_KEY in the CodePathfinder environment.")
        self.stdout.write("Generate with:  openssl genrsa 4096")

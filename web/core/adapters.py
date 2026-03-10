import re

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse
from django.contrib.sites.shortcuts import get_current_site

User = get_user_model()

def notify_admins_of_new_user(request, user):
    """
    Sends an email to all superusers when a new user registers.
    """
    # Get all superusers (admin emails)
    admins = User.objects.filter(is_superuser=True).values_list('email', flat=True)
    if not admins:
        return

    # Construct the activation URL
    # Assuming 'admin_user_edit' is the URL name for the user edit page
    # and it takes 'pk' as an argument.
    path = reverse('admin_user_edit', args=[user.pk])
    
    # Try to build a full absolute URL
    if request:
        protocol = 'https' if request.is_secure() else 'http'
        domain = get_current_site(request).domain
        # Ensure domain doesn't have protocol
        if '://' in domain:
             domain = domain.split('://')[1]
             
        activation_url = f"{protocol}://{domain}{path}"
    else:
        # Fallback if no request available
        activation_url = path

    subject = f"New User Registration: {user.username}"
    message = (
        f"A new user has registered and is pending approval.\n\n"
        f"Username: {user.username}\n"
        f"Email: {user.email}\n"
        f"Join Date: {user.date_joined}\n\n"
        f"To approve this user, please visit:\n{activation_url}\n\n"
        f"Or go to the User Management page in the application."
    )
    
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@codepathfinder.com')
    
    send_mail(
        subject,
        message,
        from_email,
        list(admins),
        fail_silently=True,
    )

class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """
        Allow new signups.
        """
        return True
    
    def get_signup_redirect_url(self, request):
        """Redirect signup attempts to the projects page."""
        return reverse('project_list')

    def save_user(self, request, user, form, commit=True):
        """
        This is called when saving a new user via normal registration.
        """
        user = super().save_user(request, user, form, commit=False)
        user.is_active = True  # Activate by default
        if commit:
            user.save()
            notify_admins_of_new_user(request, user)
        return user

class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def get_app(self, request, provider, *args, **kwargs):
        """
        Override to handle missing social apps gracefully.
        Returns None if no app is configured, preventing DoesNotExist errors.
        """
        try:
            return super().get_app(request, provider, *args, **kwargs)
        except Exception:
            # If no social app is configured, return None instead of raising an error
            # This allows the login page to load without social login buttons
            return None
    
    def list_providers(self, request, *args, **kwargs):
        """
        Override to return empty list if no social apps are configured.
        This prevents errors when templates try to list providers.
        """
        try:
            return super().list_providers(request, *args, **kwargs)
        except Exception:
            return []
    
    def populate_user(self, request, sociallogin, data):
        """
        Populate user instance from social account data.
        Override to generate username from last_name instead of first_name.
        """
        user = super().populate_user(request, sociallogin, data)

        # Generate username based on last name (or fall back to first name, then email)
        last_name = data.get('last_name', '').strip()
        first_name = data.get('first_name', '').strip()
        email = data.get('email', '').strip()

        if last_name:
            base_username = last_name.lower()
        elif first_name:
            base_username = first_name.lower()
        elif email:
            base_username = email.split('@')[0].lower()
        else:
            base_username = 'user'

        # Remove any non-alphanumeric characters except underscores
        base_username = re.sub(r'[^\w]', '', base_username)

        # Ensure username is unique by appending a number if necessary
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        user.username = username
        return user

    def is_open_for_signup(self, request, sociallogin):
        """
        Allow new OAuth signups.
        """
        return True
    
    def authentication_error(self, request, provider_id, error=None, exception=None, extra_context=None):
        """Handle authentication errors by redirecting to beta page."""
        from django.shortcuts import redirect
        return redirect('beta_signup')
    
    def save_user(self, request, sociallogin, form=None):
        """
        This is called when saving a new user via OAuth.
        Only reached if is_open_for_signup returns True (existing user).
        """
        user = super().save_user(request, sociallogin, form)
        # Note: super().save_user() saves the user instance.
        
        # Explicitly set inactive and save again
        # Default behavior is now active, so we don't need to force inactive
        if not user.is_active:
             # Only modify if for some reason it's not active (though default model might say otherwise, 
             # AbstractUser defaults to True usually, but let's be safe and ensure it's True if that's the goal)
             user.is_active = True
             user.save()
            
        notify_admins_of_new_user(request, user)
        return user


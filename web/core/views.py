from django.db.models import Count
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.views.generic import CreateView, ListView, TemplateView, View, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy, reverse
from django.core.mail import send_mail
from django.contrib import messages
from django.core import signing
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.http import JsonResponse
from django.conf import settings
from .forms import RegistrationForm, UserEditForm, SystemSettingsForm
from .models import SystemSettings, UserGitHubSettings
from django.contrib.auth import get_user_model
from projects.utils import stop_indexer_job
import json
import logging

# Unused imports removed after LLM provider features were removed:
# - LLMProvider, LLMModel (no longer needed)
# - asyncio, time, threading, os, yaml (were used by LLM test and config endpoints)
# - sync_to_async (was used by LLM test endpoint)
# - csrf_exempt, method_decorator (were used by LibreChatConfigView)
# - require_http_methods (was unused)

logger = logging.getLogger(__name__)

User = get_user_model()

class BetaSignupView(View):
    """
    View for Private Beta signup form.
    New users fill out this form to request access to CodePathfinder.
    Form submissions are emailed to the admin for review.
    """
    template_name = 'core/beta_signup.html'
    
    def get(self, request):
        return render(request, self.template_name, {'form': {}})
    
    def post(self, request):
        # Get form data
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        github_repo = request.POST.get('github_repo', '').strip()
        interest = request.POST.get('interest', '').strip()
        
        # Simple validation
        errors = {}
        if not name:
            errors['name'] = ['Name is required.']
        if not email:
            errors['email'] = ['Email is required.']
        
        if errors:
            return render(request, self.template_name, {
                'form': {
                    'errors': True,
                    'name': type('obj', (object,), {'value': name, 'errors': errors.get('name', [])}),
                    'email': type('obj', (object,), {'value': email, 'errors': errors.get('email', [])}),
                    'github_repo': type('obj', (object,), {'value': github_repo, 'errors': errors.get('github_repo', [])}),
                    'interest': type('obj', (object,), {'value': interest, 'errors': errors.get('interest', [])}),
                }
            })
        
        # Create signed approval token (valid for 7 days)
        approval_data = {
            'name': name,
            'email': email,
            'github_repo': github_repo,
        }
        token = signing.dumps(approval_data, salt='beta-approval')
        
        # Build approval URL
        approval_path = reverse('approve_beta_user', kwargs={'token': token})
        approval_url = f"https://codepathfinder.com{approval_path}"
        
        # Send email to admin
        subject = f"🚀 Private Beta Application: {name}"
        message = f"""
New Private Beta Application for CodePathfinder!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📧 APPLICANT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Name: {name}
Email: {email}
GitHub Repository: {github_repo}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 INTEREST / USE CASE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{interest}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ ONE-CLICK APPROVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Click to instantly create their account:
{approval_url}

(Link expires in 7 days)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        try:
            send_mail(
                subject,
                message,
                'noreply@codepathfinder.com',
                ['tom@codepathfinder.com'],
                fail_silently=False,
            )
        except Exception as e:
            # Log the error but still show success to user
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to send beta signup email: {e}")
        
        # Show success page
        return render(request, self.template_name, {
            'success': True,
            'submitted_email': email,
        })


class ApproveBetaUserView(View):
    """
    View for approving beta applications via secure signed link.
    Creates a user account and sends welcome email with login credentials.
    """
    template_name = 'core/beta_approved.html'
    
    def get(self, request, token):
        try:
            # Decode the signed token (valid for 7 days = 604800 seconds)
            data = signing.loads(token, salt='beta-approval', max_age=604800)
            name = data['name']
            email = data['email']
            github_repo = data.get('github_repo', '')
        except signing.SignatureExpired:
            messages.error(request, 'This approval link has expired.')
            return redirect('home')
        except signing.BadSignature:
            messages.error(request, 'Invalid approval link.')
            return redirect('home')
        
        # Check if user already exists
        if User.objects.filter(email=email).exists():
            messages.warning(request, f'User with email {email} already exists.')
            return redirect('admin_user_list')
        
        # Generate a random password
        password = get_random_string(12)
        
        # Create username from email (before the @)
        username = email.split('@')[0]
        # Ensure unique username
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        # Create the user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_active=True
        )
        
        # Send welcome email to the new user
        welcome_subject = "🎉 Welcome to CodePathfinder!"
        welcome_message = f"""
Hi {name}!

Great news - your CodePathfinder Private Beta application has been approved!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔐 YOUR LOGIN CREDENTIALS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Login URL: https://codepathfinder.com/accounts/login/
Username: {username}
Password: {password}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You can also sign in with Google if your email matches.

After logging in, we recommend:
1. Create your first project by adding a GitHub repository
2. Run the indexer to build your semantic search index  
3. Check out the Docs for Claude Desktop integration

Happy coding!

- The CodePathfinder Team
"""
        
        try:
            send_mail(
                welcome_subject,
                welcome_message,
                'tom@codepathfinder.com',
                [email],
                fail_silently=False,
            )
            messages.success(request, f'User {email} created and welcome email sent!')
        except Exception as e:
            messages.warning(request, f'User {email} created but welcome email failed to send. Password: {password}')
        
        return redirect('admin_user_list')


def is_social_account_user(user):
    """Check if user has any linked social accounts"""
    try:
        return user.socialaccount_set.exists()
    except:
        return False

class RegisterView(CreateView):
    form_class = RegistrationForm
    template_name = 'registration/register.html'
    success_url = reverse_lazy('login')

    def form_valid(self, form):
        response = super().form_valid(form)
        # Send email to admin
        send_mail(
            'New User Registration',
            f'User {self.object.username} ({self.object.email}) has registered and needs approval.',
            'system@codepathfinder.local',
            ['tom@grabowski.org'],
            fail_silently=False,
        )
        messages.success(self.request, 'Account created successfully. Please wait for admin approval.')
        return response

class AdminUserListView(LoginRequiredMixin, ListView):
    model = User
    template_name = 'core/admin_user_list.html'
    context_object_name = 'users'

    def get_queryset(self):
        base_qs = User.objects.select_related(
            'github_settings',
        ).annotate(
            project_count=Count('projects', distinct=True),
        )
        # Superusers see all users
        if self.request.user.is_superuser:
            return base_qs.order_by('-date_joined')
        # Standard users only see themselves
        return base_qs.filter(pk=self.request.user.pk)

    def post(self, request, *args, **kwargs):
        # Only superusers can perform actions from the list view
        if not request.user.is_superuser:
            messages.error(request, "Permission denied.")
            return redirect('admin_user_list')

        user_id = request.POST.get('user_id')
        action = request.POST.get('action')
        if user_id and action:
            try:
                user = User.objects.get(pk=user_id)
                if action == 'enable':
                    user.is_active = True
                    messages.success(request, f'User {user.username} enabled.')
                elif action == 'disable':
                    user.is_active = False
                    messages.success(request, f'User {user.username} disabled.')
                user.save()
            except User.DoesNotExist:
                messages.error(request, 'User not found.')
        return redirect('admin_user_list')

class DocumentationView(TemplateView):
    def get_template_names(self):
        # Show simplified public docs for anonymous users
        if not self.request.user.is_authenticated:
            return ['core/documentation_public.html']
        return ['core/documentation.html']

class SSOLogoutView(View):
    """Clear Django session then chain to LibreChat logout.

    LibreChat's OPENID_USE_END_SESSION_ENDPOINT will subsequently redirect to
    /o/logout/ (RP-Initiated Logout) which finally lands back on the home page.
    """

    def get(self, request):
        logout(request)
        return redirect('home')


class LandingPageView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('project_list')
        return render(request, 'core/landing.html')

class AboutView(TemplateView):
    template_name = 'core/about.html'



class DeleteAccountView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        # Stop all running jobs for the user's projects
        for project in user.projects.all():
            stop_indexer_job(project)
            # Project deletion will be handled by cascade, but we stopped the jobs first
        
        # Delete the user (this cascades to projects)
        user.delete()
        messages.success(request, "Your account and all associated data have been deleted.")
        return redirect('home')

class AdminUserCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = User
    form_class = RegistrationForm
    template_name = 'core/admin_user_form.html'
    success_url = reverse_lazy('admin_user_list')

    def test_func(self):
        return self.request.user.is_superuser

    def form_valid(self, form):
        # Save the user but don't log them in (unlike RegisterView)
        self.object = form.save()
        messages.success(self.request, f"User {self.object.username} created successfully.")
        return redirect(self.success_url)

class AdminUserUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = User
    form_class = UserEditForm
    template_name = 'core/admin_user_form.html'
    success_url = reverse_lazy('admin_user_list')
    context_object_name = 'user_obj'

    def test_func(self):
        # Allow superusers OR the user themselves
        return self.request.user.is_superuser or self.get_object() == self.request.user

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        user_obj = self.get_object()
        kwargs['is_social_account'] = is_social_account_user(user_obj)
        # Pass existing GitHub settings to form
        github_settings = getattr(user_obj, 'github_settings', None)
        kwargs['github_settings'] = github_settings
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_obj = self.get_object()
        context['is_social_account'] = is_social_account_user(user_obj)

        # Get social account for profile picture
        if context['is_social_account']:
            context['social_account'] = user_obj.socialaccount_set.first()

        # Get GitHub settings for display
        context['github_settings'] = getattr(user_obj, 'github_settings', None)

        return context

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # If not superuser, disable is_superuser and is_active fields
        if not self.request.user.is_superuser:
            if 'is_superuser' in form.fields:
                form.fields['is_superuser'].disabled = True
            if 'is_active' in form.fields:
                form.fields['is_active'].disabled = True
        return form

    def form_valid(self, form):
        user_obj = form.save(commit=False)

        # If password was changed and it's the current user, update session
        if form.cleaned_data.get('password1') and user_obj == self.request.user:
            from django.contrib.auth import update_session_auth_hash
            user_obj.save()
            update_session_auth_hash(self.request, user_obj)
            messages.success(self.request, f"User {user_obj.username} and password updated successfully.")
        else:
            user_obj.save()
            if form.cleaned_data.get('password1'):
                messages.success(self.request, f"User {user_obj.username} and password updated successfully.")
            else:
                messages.success(self.request, f"User {user_obj.username} updated successfully.")

        # Save GitHub settings (including personal skills repo)
        github_username = form.cleaned_data.get('github_username', '')
        github_token = form.cleaned_data.get('github_token', '')
        skills_repo_url = self.request.POST.get('skills_repo_url', '').strip()
        skills_repo_branch = self.request.POST.get('skills_repo_branch', 'main').strip() or 'main'
        if github_username or github_token or skills_repo_url:
            github_settings, created = UserGitHubSettings.objects.get_or_create(user=user_obj)
            if github_username:
                github_settings.github_username = github_username
            if github_token:
                github_settings.github_token = github_token
            github_settings.skills_repo_url = skills_repo_url or None
            github_settings.skills_repo_branch = skills_repo_branch
            github_settings.save()

        return redirect(self.success_url)

class AdminUserDeleteView(LoginRequiredMixin, UserPassesTestMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)

        # Prevent deleting yourself
        if user == request.user:
            messages.error(request, "You cannot delete your own account from here.")
            return redirect('admin_user_list')

        # Stop all running jobs for the user's projects
        for project in user.projects.all():
            stop_indexer_job(project)

        username = user.username
        user.delete()
        messages.success(request, f"User {username} and all associated data have been deleted.")
        return redirect('admin_user_list')

    def test_func(self):
        return self.request.user.is_superuser


class AdminSettingsView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Admin view for configuring global system settings."""
    template_name = 'core/admin_settings_form.html'

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request):
        settings_obj = SystemSettings.get_settings()
        form = SystemSettingsForm(instance=settings_obj)
        return render(request, self.template_name, {
            'form': form,
            'settings': settings_obj,
        })

    def post(self, request):
        settings_obj = SystemSettings.get_settings()
        form = SystemSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, 'System settings saved successfully.')
            return redirect('admin_settings')
        return render(request, self.template_name, {
            'form': form,
            'settings': settings_obj,
        })

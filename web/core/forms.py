from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import SystemSettings, UserGitHubSettings

User = get_user_model()

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text="Required. Organization email.")
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = False  # Deactivate account until admin approval
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    """Form for editing users with optional password change and GitHub settings."""
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Leave blank to keep current password'}),
        required=False,
        label='Password',
        help_text='Your password must contain at least 8 characters.'
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Leave blank to keep current password'}),
        required=False,
        label='Password confirmation',
        help_text='Enter the same password as before, for verification.'
    )

    # GitHub settings fields
    github_username = forms.CharField(
        max_length=255,
        required=False,
        label='GitHub Username',
        help_text='Your GitHub username for API operations.'
    )
    github_token = forms.CharField(
        max_length=255,
        required=False,
        label='GitHub Token',
        widget=forms.PasswordInput(attrs={'placeholder': 'ghp_...', 'class': 'form-control'}, render_value=True),
        help_text='Personal Access Token with repo permissions.'
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_superuser']

    def __init__(self, *args, **kwargs):
        self.is_social_account = kwargs.pop('is_social_account', False)
        self.github_settings = kwargs.pop('github_settings', None)
        super().__init__(*args, **kwargs)

        # Populate GitHub fields from existing settings
        if self.github_settings:
            self.fields['github_username'].initial = self.github_settings.github_username
            self.fields['github_token'].initial = self.github_settings.github_token
        
        # Add form-control class to all fields
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-control'
        
        # If social account, remove password fields
        if self.is_social_account:
            del self.fields['password1']
            del self.fields['password2']
            # Also disable username/email/name editing for OAuth users
            self.fields['username'].widget.attrs['readonly'] = True
            self.fields['email'].widget.attrs['readonly'] = True
            self.fields['first_name'].widget.attrs['readonly'] = True
            self.fields['last_name'].widget.attrs['readonly'] = True
    
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        
        # Only validate if password fields are present and at least one is filled
        if not self.is_social_account and (password1 or password2):
            if password1 != password2:
                raise forms.ValidationError('Passwords do not match.')
            
            if password1 and len(password1) < 8:
                raise forms.ValidationError('Password must be at least 8 characters long.')
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)

        # Only set password if it was provided
        password = self.cleaned_data.get('password1')
        if password:
            user.set_password(password)

        if commit:
            user.save()
        return user


class SystemSettingsForm(forms.ModelForm):
    """Form for editing global system settings (superuser only)."""

    class Meta:
        model = SystemSettings
        exclude = ['updated_by', 'updated_at']
        widgets = {
            'elasticsearch_password': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': '••••••••'},
                render_value=True
            ),
            'elasticsearch_api_key': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': '••••••••'},
                render_value=True
            ),
            'skills_repo_token': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': '••••••••'},
                render_value=True
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add form-control class to all non-password fields
        for name, field in self.fields.items():
            if 'class' not in field.widget.attrs:
                field.widget.attrs['class'] = 'form-control'

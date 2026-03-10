from django import forms
from .models import PathfinderProject

class ProjectForm(forms.ModelForm):
    class Meta:
        model = PathfinderProject
        fields = [
            'name',
            'repository_url',
            'github_token',
            'branch',
            'custom_index_name',
            'clean_index',
            'pull_before_index',
            'watch_mode'
        ]
        widgets = {
            'github_token': forms.PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'ghp_xxxxxxxxxxxx (optional)'
            }),
        }
        help_texts = {
            'name': 'A descriptive name for your project',
            'repository_url': 'GitHub repository URL (e.g., https://github.com/user/repo.git)',
            'github_token': 'Personal Access Token for private repositories (leave empty for public repos)',
            'branch': 'Specific branch to index (leave empty to auto-detect)',
            'custom_index_name': 'Custom Elasticsearch index name (leave empty for auto-generated)',
            'clean_index': 'Delete existing index before starting - use for full rebuild',
            'pull_before_index': 'Git pull before indexing - use for incremental updates',
            'watch_mode': 'Keep indexer running for continuous updates',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default value for clean_index
        if 'clean_index' in self.fields:
             self.fields['clean_index'].initial = True

        # Show placeholder hint if token is already set (for editing existing projects)
        if self.instance and self.instance.pk and self.instance.github_token:
            token = self.instance.github_token
            # Show first 7 and last 4 characters for verification (e.g., "ghp_XW0...Ztth")
            if len(token) > 12:
                masked_token = f"{token[:7]}...{token[-4:]}"
            else:
                masked_token = f"{token[:3]}...{token[-2:]}" if len(token) > 5 else "•••"
            self.fields['github_token'].widget.attrs['placeholder'] = '••••••••••••••••••••••••••••••••••••••••'
            self.fields['github_token'].help_text = f'Current token: {masked_token}. Leave empty to keep, or enter a new one to replace.'

        # Add Bootstrap classes to all form fields
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            elif not isinstance(field.widget, forms.PasswordInput):
                field.widget.attrs['class'] = 'form-control'

            # Add placeholder for text inputs
            if field_name == 'name':
                field.widget.attrs['placeholder'] = 'My Code Project'
            elif field_name == 'repository_url':
                field.widget.attrs['placeholder'] = 'https://github.com/google/styleguide'
            elif field_name == 'branch':
                field.widget.attrs['placeholder'] = 'main (optional)'
            elif field_name == 'custom_index_name':
                field.widget.attrs['placeholder'] = 'my-custom-index (optional)'

    def clean_github_token(self):
        """
        Preserve existing token if field is left empty during update.
        PasswordInput widgets don't display existing values for security,
        so we need to keep the original token if user doesn't enter a new one.
        """
        new_token = self.cleaned_data.get('github_token')

        # If editing an existing project and no new token was entered,
        # preserve the existing token
        if self.instance and self.instance.pk:
            if not new_token:
                return self.instance.github_token

        return new_token

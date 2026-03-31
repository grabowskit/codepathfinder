"""
Skills views for CodePathfinder.

Provides views for listing, viewing, creating, and managing AI agent skills.
"""
import json
import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.db.models import Q
from django import forms

from .models import Skill, SkillUsage
from .services import SkillService, SkillSyncError, SkillPushError

logger = logging.getLogger(__name__)


class SkillForm(forms.ModelForm):
    """Form for creating and editing skills."""

    class Meta:
        model = Skill
        fields = ['name', 'description', 'instructions', 'allowed_tools', 'tags', 'is_curated']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., code-review, test-generator'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Brief description of what this skill does'
            }),
            'instructions': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 15,
                'placeholder': 'Full instructions/prompt for the AI agent...'
            }),
            'allowed_tools': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '["semantic_code_search", "read_file_from_chunks"]'
            }),
            'tags': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': '["python", "testing", "code-quality"]'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Only superusers can set is_curated
        if self.user and not self.user.is_superuser:
            self.fields['is_curated'].disabled = True

    def clean_allowed_tools(self):
        """Parse allowed_tools as JSON list."""
        import json
        value = self.cleaned_data.get('allowed_tools')
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise forms.ValidationError('Must be a JSON array')
            return parsed
        except json.JSONDecodeError:
            raise forms.ValidationError('Invalid JSON format. Use ["tool1", "tool2"]')

    def clean_tags(self):
        """Parse tags as JSON list."""
        import json
        value = self.cleaned_data.get('tags')
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise forms.ValidationError('Must be a JSON array')
            return parsed
        except json.JSONDecodeError:
            raise forms.ValidationError('Invalid JSON format. Use ["tag1", "tag2"]')


class SkillListView(LoginRequiredMixin, ListView):
    """List all available skills."""
    model = Skill
    template_name = 'skills/skill_list.html'
    context_object_name = 'skills'

    def get_queryset(self):
        user = self.request.user
        scope_filter = self.request.GET.get('scope', 'all')

        # Base queryset depends on scope filter
        if scope_filter == 'personal':
            queryset = Skill.objects.filter(is_active=True, scope='personal', created_by=user)
        elif scope_filter == 'global':
            queryset = Skill.objects.filter(is_active=True, scope='global')
        else:
            # 'all': global + user's personal skills
            queryset = Skill.objects.filter(is_active=True).filter(
                Q(scope='global') |
                Q(scope='personal', created_by=user)
            )

        # Filter hidden skills - only superusers can see hidden skills
        if not user.is_superuser:
            queryset = queryset.filter(is_hidden=False)

        # Filter by tag if provided (special handling for "curated" tag)
        tag = self.request.GET.get('tag')
        if tag:
            if tag == 'curated':
                queryset = queryset.filter(is_curated=True)
            else:
                queryset = queryset.filter(tags__contains=tag)

        # Search
        search = self.request.GET.get('q')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search) |
                Q(tags__icontains=search)
            )

        # Sorting
        sort_by = self.request.GET.get('sort', 'name')
        sort_order = self.request.GET.get('order', 'asc')

        valid_sort_fields = ['name', 'usage_count']
        if sort_by not in valid_sort_fields:
            sort_by = 'name'

        if sort_by == 'name':
            queryset = queryset.order_by('-name' if sort_order == 'desc' else 'name')
        elif sort_by == 'usage_count':
            if sort_order == 'desc':
                queryset = queryset.order_by('-usage_count', 'name')
            else:
                queryset = queryset.order_by('usage_count', 'name')

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['tag_filter'] = self.request.GET.get('tag', '')
        context['curated_filter'] = self.request.GET.get('curated', '')
        context['search_query'] = self.request.GET.get('q', '')
        context['show_hidden'] = self.request.GET.get('show_hidden', '')
        context['sort_by'] = self.request.GET.get('sort', 'name')
        context['sort_order'] = self.request.GET.get('order', 'asc')
        context['scope_filter'] = self.request.GET.get('scope', 'all')

        # Count personal skills for current user
        context['personal_skill_count'] = Skill.objects.filter(
            is_active=True, scope='personal', created_by=user
        ).count()

        # Get all unique tags from visible skills (global + user's personal)
        all_skills = Skill.objects.filter(is_active=True).filter(
            Q(scope='global') | Q(scope='personal', created_by=user)
        )
        if not user.is_superuser:
            all_skills = all_skills.filter(is_hidden=False)
        all_tags = set()
        for skill in all_skills:
            if skill.tags:
                all_tags.update(skill.tags)
        context['all_tags'] = sorted(all_tags)
        return context


# Import models for Q
from django.db import models


class SkillDetailView(LoginRequiredMixin, DetailView):
    """View skill details."""
    model = Skill
    template_name = 'skills/skill_detail.html'
    context_object_name = 'skill'

    def get_object(self):
        user = self.request.user
        name = self.kwargs['name']
        # Allow access to global skills or the user's own personal skills
        skill = Skill.objects.filter(is_active=True, name=name).filter(
            Q(scope='global') | Q(scope='personal', created_by=user)
        ).first()
        if not skill:
            from django.http import Http404
            raise Http404("Skill not found")
        return skill

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        skill = self.object
        user = self.request.user
        # Can user edit this skill?
        context['can_edit'] = (
            user.is_superuser or
            (skill.scope == 'personal' and skill.created_by == user)
        )
        # Can user fork this skill (copy to personal)?
        context['can_fork'] = skill.scope == 'global'
        return context


class SkillCreateView(LoginRequiredMixin, CreateView):
    """Create a new skill."""
    model = Skill
    form_class = SkillForm
    template_name = 'skills/skill_form.html'
    success_url = reverse_lazy('skill_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Skill "{form.instance.name}" created successfully.')
        return super().form_valid(form)


class SkillUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """Edit an existing skill. Only superusers can edit global skills; users can edit their personal skills."""
    model = Skill
    form_class = SkillForm
    template_name = 'skills/skill_form.html'
    success_url = reverse_lazy('skill_list')

    def get_object(self):
        return get_object_or_404(Skill, name=self.kwargs['name'])

    def test_func(self):
        skill = self.get_object()
        return (
            self.request.user.is_superuser or
            (skill.scope == 'personal' and skill.created_by == self.request.user)
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f'Skill "{form.instance.name}" updated successfully.')
        return super().form_valid(form)


class SkillDeleteView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    Delete a skill (soft delete by setting is_hidden=True).

    The skill is NOT removed from the database or GitHub repository.
    Instead, it's marked as hidden so it can be restored later by
    changing the metadata in GitHub or via admin action.
    """

    def post(self, request, name):
        from django.utils import timezone

        skill = get_object_or_404(Skill, name=name)
        skill.is_hidden = True
        skill.deleted_at = timezone.now()
        skill.deleted_by = request.user
        skill.save(update_fields=['is_hidden', 'deleted_at', 'deleted_by'])
        messages.success(request, f'Skill "{skill.name}" has been deleted. It can be restored from GitHub or by an administrator.')
        return redirect('skill_list')

    def test_func(self):
        skill = get_object_or_404(Skill, name=self.kwargs['name'])
        return (
            self.request.user.is_superuser or
            skill.created_by == self.request.user
        )


class SkillSyncView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Bi-directional sync: Pull from GitHub AND push local skills to GitHub (admin only)."""

    def test_func(self):
        return self.request.user.is_superuser

    def post(self, request):
        try:
            service = SkillService()
            results = service.sync_skills()
            
            # Build success message
            msg_parts = []
            if results['pulled']:
                msg_parts.append(f"Pulled {len(results['pulled'])} skills from GitHub")
            if results['pushed']:
                msg_parts.append(f"Pushed {len(results['pushed'])} skills to GitHub")
            
            if msg_parts:
                messages.success(request, '. '.join(msg_parts) + '.')
            else:
                messages.info(request, 'Sync completed. No changes detected.')
            
            # Show any errors as warnings
            for error in results.get('errors', []):
                messages.warning(request, error)
                
        except SkillSyncError as e:
            messages.error(request, f'Sync failed: {str(e)}')
        except Exception as e:
            logger.exception("Unexpected error during skill sync")
            messages.error(request, f'Unexpected error during sync: {str(e)}')

        return redirect('skill_list')


# ============================================================================
# API Views for Chat Skill Selector
# ============================================================================

class SkillSearchAPIView(LoginRequiredMixin, View):
    """
    JSON API for typeahead skill search.

    GET /skills/api/search/?q=<query>&limit=10

    Returns JSON with matching skills for the skill selector dropdown.
    Includes the user's personal skills alongside global skills.
    Hidden skills are excluded unless user is superuser.
    """

    def get(self, request):
        query = request.GET.get('q', '').strip()
        limit = min(int(request.GET.get('limit', 10)), 20)  # Cap at 20
        user = request.user

        # Include global skills + user's personal skills
        skills = Skill.objects.filter(is_active=True).filter(
            Q(scope='global') | Q(scope='personal', created_by=user)
        )

        # Exclude hidden skills for non-superusers
        if not user.is_superuser:
            skills = skills.filter(is_hidden=False)

        if query:
            skills = skills.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(tags__icontains=query)
            )

        skills = skills.order_by('-is_curated', '-usage_count', 'name')[:limit]

        return JsonResponse({
            'skills': [
                {
                    'id': s.id,
                    'name': s.name,
                    'description': s.description[:150] if s.description else '',
                    'is_curated': s.is_curated,
                    'tags': s.tags[:5] if s.tags else [],
                    'usage_count': s.usage_count,
                    'scope': s.scope,
                }
                for s in skills
            ]
        })


class TopSkillsAPIView(LoginRequiredMixin, View):
    """
    Get top skills for a user based on their usage history.
    Falls back to global popularity for users with no history.

    GET /skills/api/top/?limit=6

    Returns JSON with personalized skill cards for the Chat interface.
    Hidden skills are excluded unless user is superuser.
    """

    def get(self, request):
        limit = min(int(request.GET.get('limit', 6)), 10)  # Cap at 10
        user = request.user

        # Build base queryset: global + user's personal skills
        base_qs = Skill.objects.filter(is_active=True).filter(
            Q(scope='global') | Q(scope='personal', created_by=user)
        )
        if not user.is_superuser:
            base_qs = base_qs.filter(is_hidden=False)

        # Try user's recent skills first (ordered by usage count, then recency)
        user_usages = SkillUsage.objects.filter(
            user=user,
            skill__in=base_qs,
        ).select_related('skill').order_by('-usage_count', '-used_at')[:limit]

        if user_usages.exists():
            skills = [usage.skill for usage in user_usages]
            personalized = True
        else:
            # Fallback: global popularity (curated first, then by usage count)
            skills = list(base_qs.order_by('-is_curated', '-usage_count', 'name')[:limit])
            personalized = False

        return JsonResponse({
            'skills': [
                {
                    'id': s.id,
                    'name': s.name,
                    'description': s.description[:100] if s.description else '',
                    'is_curated': s.is_curated,
                    'tags': s.tags[:3] if s.tags else [],
                    'scope': s.scope,
                }
                for s in skills
            ],
            'personalized': personalized
        })


class SkillToggleVisibilityView(LoginRequiredMixin, View):
    """
    Toggle skill visibility (hide/show) for administrators.
    
    POST /skills/api/toggle-visibility/<skill_id>/
    
    Hidden skills are not visible in UI, API, or MCP for regular users.
    Only superusers can see and manage hidden skills.
    """
    
    def post(self, request, skill_id):
        # Only superusers can toggle visibility
        if not request.user.is_superuser:
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        try:
            skill = Skill.objects.get(id=skill_id)
            skill.is_hidden = not skill.is_hidden
            skill.save(update_fields=['is_hidden'])
            
            return JsonResponse({
                'success': True,
                'skill_id': skill.id,
                'is_hidden': skill.is_hidden,
                'message': f"Skill '{skill.name}' is now {'hidden' if skill.is_hidden else 'visible'}"
            })
        except Skill.DoesNotExist:
            return JsonResponse({'error': 'Skill not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class AvailableToolsAPIView(LoginRequiredMixin, View):
    """
    Get list of available MCP tools for the skill builder.

    GET /skills/api/tools/

    Returns JSON with all available tools and their descriptions.
    """

    def get(self, request):
        from mcp_server.tools import TOOL_DEFINITIONS

        tools = [
            {
                'name': tool['name'],
                'description': tool.get('description', '')[:200],  # Truncate long descriptions
            }
            for tool in TOOL_DEFINITIONS
        ]

        return JsonResponse({'tools': tools})


class SkillImportView(LoginRequiredMixin, View):
    """
    Import skills from SKILL.md formatted content or multiple files.

    POST /skills/import/

    Accepts:
    - JSON body: {"content": "---\\nname: ...\\n---\\n# Instructions..."}
    - Form data: content field or file upload (single or multiple)

    SKILL.md format:
    ---
    name: skill-name
    description: Brief description
    allowed-tools:
      - semantic_code_search
      - read_file_from_chunks
    tags:
      - code-quality
    ---
    # Instructions

    Full instructions for the AI agent...

    OR Markdown format:
    # skill-name
    
    Brief description on the next line.
    
    ## Description
    More detailed description...
    
    ## Instructions
    Full instructions for the AI agent...
    """

    def post(self, request):
        try:
            # Handle multiple file uploads
            files = request.FILES.getlist('files')
            if files:
                return self._handle_multiple_files(request, files)
            
            # Handle single file or content
            if request.content_type == 'application/json':
                try:
                    data = json.loads(request.body)
                    content = data.get('content', '')
                except json.JSONDecodeError:
                    return JsonResponse({'error': 'Invalid JSON body'}, status=400)
            else:
                content = request.POST.get('content', '')
                if not content and 'file' in request.FILES:
                    content = request.FILES['file'].read().decode('utf-8')

            if not content or not content.strip():
                return JsonResponse({'error': 'No content provided'}, status=400)

            # Import single skill
            result = self._import_skill_content(request, content)
            if 'error' in result:
                return JsonResponse(result, status=result.get('status', 400))
            return JsonResponse(result)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    def _handle_multiple_files(self, request, files):
        """Handle import of multiple files."""
        service = SkillService()
        imported = []
        context_files = []
        errors = []
        
        # First pass: identify skill files vs context files
        file_contents = []
        for f in files:
            try:
                content = f.read().decode('utf-8')
                file_contents.append({
                    'name': f.name,
                    'content': content,
                    'is_skill': self._is_skill_file(content)
                })
            except Exception as e:
                errors.append(f"Failed to read {f.name}: {str(e)}")
        
        # Import skill files
        for fc in file_contents:
            if fc['is_skill']:
                try:
                    skill_data = service.parse_skill_md(fc['content'])
                    if not skill_data:
                        skill_data = self._parse_markdown_skill(fc['content'], fc['name'])
                    
                    if skill_data and skill_data.get('name'):
                        # Check permissions
                        existing = Skill.objects.filter(name=skill_data['name']).first()
                        if existing and existing.created_by != request.user and not request.user.is_superuser:
                            errors.append(f"Skill '{skill_data['name']}' belongs to another user")
                            continue
                        
                        # Create or update
                        skill, created = Skill.objects.update_or_create(
                            name=skill_data['name'],
                            defaults={
                                'description': skill_data.get('description', ''),
                                'instructions': skill_data.get('instructions', ''),
                                'allowed_tools': skill_data.get('allowed_tools', []),
                                'tags': skill_data.get('tags', []),
                                'created_by': request.user if not existing else existing.created_by,
                                'is_active': True,
                            }
                        )
                        imported.append({
                            'name': skill.name,
                            'created': created,
                            'file': fc['name']
                        })
                except Exception as e:
                    errors.append(f"Failed to import {fc['name']}: {str(e)}")
            else:
                context_files.append(fc['name'])
        
        if not imported:
            return JsonResponse({
                'error': 'No valid skill files found',
                'context_files': context_files,
                'errors': errors
            }, status=400)
        
        return JsonResponse({
            'success': True,
            'imported': len(imported),
            'skills': imported,
            'context_files': context_files,
            'errors': errors,
            'message': f"Successfully imported {len(imported)} skill(s)"
        })

    def _is_skill_file(self, content):
        """Check if content appears to be a skill definition."""
        # Check for YAML frontmatter skill format
        if content.strip().startswith('---'):
            import re
            if re.search(r'^name\s*:', content, re.MULTILINE):
                return True
        
        # Check for Markdown skill format
        import re
        has_name = bool(re.search(r'^#\s+\w+', content, re.MULTILINE))
        has_desc = bool(re.search(r'^##\s*description', content, re.MULTILINE | re.IGNORECASE))
        has_instr = bool(re.search(r'^##\s*instructions?', content, re.MULTILINE | re.IGNORECASE))
        
        return has_name and (has_desc or has_instr)

    def _parse_markdown_skill(self, content, filename):
        """Parse a Markdown-formatted skill file."""
        import re
        
        # Extract name from # heading
        name_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if not name_match:
            return None
        
        name = name_match.group(1).strip().lower().replace(' ', '-')
        
        # Extract description from ## Description section
        desc_match = re.search(r'^##\s*description\s*\n(.*?)(?=^##|\Z)', content, re.MULTILINE | re.IGNORECASE | re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else ''
        
        # If no ## Description, use first paragraph after title
        if not description:
            after_title = content[name_match.end():].strip()
            first_para = after_title.split('\n\n')[0].strip()
            if first_para and not first_para.startswith('#'):
                description = first_para
        
        # Extract instructions from ## Instructions section
        instr_match = re.search(r'^##\s*instructions?\s*\n(.*?)(?=^##|\Z)', content, re.MULTILINE | re.IGNORECASE | re.DOTALL)
        instructions = instr_match.group(1).strip() if instr_match else ''
        
        # If no ## Instructions, use everything after ## Description or after first paragraph
        if not instructions:
            if desc_match:
                instructions = content[desc_match.end():].strip()
            else:
                parts = content.split('\n\n', 2)
                if len(parts) > 2:
                    instructions = parts[2].strip()
        
        # Extract tags from ## Tags section
        tags = []
        tags_match = re.search(r'^##\s*tags?\s*\n(.*?)(?=^##|\Z)', content, re.MULTILINE | re.IGNORECASE | re.DOTALL)
        if tags_match:
            tag_lines = tags_match.group(1).strip().split('\n')
            for line in tag_lines:
                line = line.strip().lstrip('-').strip()
                if line:
                    tags.append(line.lower())
        
        return {
            'name': name,
            'description': description,
            'instructions': instructions,
            'tags': tags,
            'allowed_tools': []
        }

    def _import_skill_content(self, request, content):
        """Import a single skill from content."""
        service = SkillService()
        
        try:
            skill_data = service.parse_skill_md(content)
        except ValueError as e:
            # Try markdown format
            skill_data = self._parse_markdown_skill(content, 'import')
            if not skill_data:
                return {'error': f'Invalid skill format: {str(e)}', 'status': 400}

        # Validate required fields
        if not skill_data.get('name'):
            return {'error': 'Skill name is required', 'status': 400}
        if not skill_data.get('description'):
            return {'error': 'Skill description is required', 'status': 400}
        if not skill_data.get('instructions'):
            return {'error': 'Skill instructions are required', 'status': 400}

        # Check for existing skill with same name
        existing = Skill.objects.filter(name=skill_data['name']).first()
        if existing:
            if existing.created_by != request.user and not request.user.is_superuser:
                return {
                    'error': f"Skill '{skill_data['name']}' already exists and belongs to another user",
                    'status': 409
                }

        # Create or update the skill
        skill, created = Skill.objects.update_or_create(
            name=skill_data['name'],
            defaults={
                'description': skill_data['description'],
                'instructions': skill_data['instructions'],
                'allowed_tools': skill_data.get('allowed_tools', []),
                'tags': skill_data.get('tags', []),
                'created_by': request.user if not existing else existing.created_by,
                'is_active': True,
            }
        )

        return {
            'success': True,
            'imported': 1,
            'skill': {
                'id': skill.id,
                'name': skill.name,
                'description': skill.description,
                'tags': skill.tags,
                'allowed_tools': skill.allowed_tools,
            },
            'created': created,
            'message': f"Skill '{skill.name}' {'created' if created else 'updated'} successfully"
        }


class SkillForkView(LoginRequiredMixin, View):
    """
    Fork a global skill to the user's personal skills.

    POST /skills/<name>/fork/

    Creates a copy of a global skill as a personal skill for the current user.
    If a personal skill with the same name already exists, redirects to it.
    """

    def post(self, request, name):
        global_skill = get_object_or_404(Skill, name=name, scope='global', is_active=True)

        # Check if user already has a personal version
        personal_name = name
        existing_personal = Skill.objects.filter(
            name=personal_name, scope='personal', created_by=request.user
        ).first()

        if existing_personal:
            messages.info(request, f'You already have a personal version of "{name}".')
            return redirect('skill_detail', name=personal_name)

        # If name conflicts with another personal skill (different user), append -custom
        if Skill.objects.filter(name=personal_name, scope='personal').exclude(created_by=request.user).exists():
            personal_name = f"{name}-custom"

        # Create the personal copy
        Skill.objects.create(
            name=personal_name,
            description=global_skill.description,
            instructions=global_skill.instructions,
            allowed_tools=global_skill.allowed_tools,
            tags=global_skill.tags,
            context_files=global_skill.context_files,
            scope='personal',
            created_by=request.user,
            is_active=True,
        )

        messages.success(request, f'"{name}" has been copied to your personal skills as "{personal_name}". You can now edit it.')
        return redirect('skill_edit', name=personal_name)


class UserSkillSyncView(LoginRequiredMixin, View):
    """
    Sync the current user's personal skills from their configured GitHub repo.

    POST /skills/sync-personal/
    """

    def post(self, request):
        try:
            service = SkillService()
            results = service.sync_user_skills(request.user)

            if results['synced']:
                messages.success(request, f"Synced {len(results['synced'])} personal skill(s) from your repository.")
            else:
                messages.info(request, 'Sync completed. No personal skills found or updated.')

            for error in results.get('errors', []):
                messages.warning(request, error)

        except SkillSyncError as e:
            messages.error(request, f'Personal skill sync failed: {str(e)}')
        except Exception as e:
            logger.exception("Unexpected error during personal skill sync")
            messages.error(request, f'Unexpected error: {str(e)}')

        return redirect('skill_list')


class ExternalImportView(LoginRequiredMixin, View):
    """
    Discover and import skills from an external GitHub repository.

    POST /skills/import-external/

    JSON body:
    - action: 'discover' or 'import'
    - repo_url: GitHub repository URL
    - branch: Branch name (default: 'main')
    - skill_names: List of skill names to import (only for action='import')
    - scope: 'global' or 'personal' (default: 'personal')
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)

        action = data.get('action')
        repo_url = data.get('repo_url', '').strip()
        branch = data.get('branch', 'main').strip() or 'main'
        scope = data.get('scope', 'personal')

        if not repo_url:
            return JsonResponse({'error': 'Repository URL is required'}, status=400)

        if action not in ('discover', 'import'):
            return JsonResponse({'error': "Action must be 'discover' or 'import'"}, status=400)

        if scope == 'global' and not request.user.is_superuser:
            return JsonResponse({'error': 'Only administrators can import to global scope'}, status=403)

        # Get user's GitHub token if available
        token = None
        try:
            if hasattr(request.user, 'github_settings') and request.user.github_settings.github_token:
                token = request.user.github_settings.github_token
        except Exception:
            pass

        service = SkillService()

        try:
            if action == 'discover':
                available = service.list_skills_from_external_repo(repo_url, branch, token)
                return JsonResponse({
                    'success': True,
                    'skills': available,
                    'count': len(available),
                })

            else:  # action == 'import'
                skill_names = data.get('skill_names', [])
                if not skill_names:
                    return JsonResponse({'error': 'No skill names provided for import'}, status=400)

                results = service.import_skills_from_external_repo(
                    repo_url=repo_url,
                    skill_names=skill_names,
                    branch=branch,
                    token=token,
                    user=request.user,
                    scope=scope,
                )
                return JsonResponse({
                    'success': True,
                    **results,
                })

        except SkillSyncError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception("External import error")
            return JsonResponse({'error': f'Unexpected error: {str(e)}'}, status=500)

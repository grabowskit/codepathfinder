"""
Memories views for CodePathfinder.
"""
import json
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from django import forms

from .models import Memory
from .services import MemoryService

logger = logging.getLogger(__name__)


class MemoryForm(forms.ModelForm):
    class Meta:
        model = Memory
        fields = ['title', 'content', 'memory_type', 'tags', 'scope']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Testing conventions'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 8, 'placeholder': 'Memory content...'}),
            'memory_type': forms.Select(attrs={'class': 'form-control'}),
            'scope': forms.Select(attrs={'class': 'form-control'}),
            'tags': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '["django", "testing"]'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not (user and user.is_staff):
            # Non-admins can only create user-scoped memories
            self.fields['scope'].choices = [(Memory.SCOPE_USER, 'User (Personal)')]
            self.fields['scope'].initial = Memory.SCOPE_USER

    def clean_tags(self):
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
            raise forms.ValidationError('Invalid JSON. Use ["tag1", "tag2"]')


class MemoryImportForm(forms.Form):
    title = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    content = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 15}))
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '["tag1", "tag2"]'})
    )
    scope = forms.ChoiceField(
        choices=Memory.SCOPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        initial=Memory.SCOPE_USER,
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not (user and user.is_staff):
            self.fields['scope'].choices = [(Memory.SCOPE_USER, 'User (Personal)')]
            self.fields['scope'].initial = Memory.SCOPE_USER

    def clean_tags(self):
        value = self.cleaned_data.get('tags', '')
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise forms.ValidationError('Must be a JSON array')
            return parsed
        except json.JSONDecodeError:
            raise forms.ValidationError('Invalid JSON. Use ["tag1", "tag2"]')


class MemoryListView(LoginRequiredMixin, View):
    template_name = 'memories/memory_list.html'

    def get(self, request):
        service = MemoryService()
        scope = request.GET.get('scope', 'all')
        tag_filter = request.GET.get('tag', '')
        type_filter = request.GET.get('type', '')
        search_q = request.GET.get('q', '')

        qs = service.list_memories(
            user=request.user,
            scope=scope if scope != 'all' else None,
            memory_type=type_filter or None,
        )
        if tag_filter:
            qs = qs.filter(tags__contains=[tag_filter])
        if search_q:
            from django.db.models import Q
            qs = qs.filter(Q(title__icontains=search_q) | Q(content__icontains=search_q))

        # Collect all tags for filter dropdown
        all_tags = set()
        for m in service.list_memories(user=request.user):
            all_tags.update(m.tags or [])

        # Also surface skill tags for unified taxonomy
        try:
            from skills.models import Skill
            for skill in Skill.objects.filter(is_active=True, is_hidden=False).values_list('tags', flat=True):
                all_tags.update(skill or [])
        except Exception:
            pass

        return render(request, self.template_name, {
            'memories': qs,
            'scope_filter': scope,
            'tag_filter': tag_filter,
            'type_filter': type_filter,
            'search_query': search_q,
            'all_tags': sorted(all_tags),
            'org_count': service.list_memories(user=request.user, scope=Memory.SCOPE_ORGANIZATION).count(),
            'user_count': service.list_memories(user=request.user, scope=Memory.SCOPE_USER).count(),
        })


class MemoryDetailView(LoginRequiredMixin, View):
    template_name = 'memories/memory_detail.html'

    def get(self, request, pk):
        service = MemoryService()
        memory = service.get_memory(pk, request.user)
        if not memory:
            messages.error(request, "Memory not found or access denied.")
            return redirect('memory_list')
        return render(request, self.template_name, {'memory': memory})


class MemoryCreateView(LoginRequiredMixin, View):
    template_name = 'memories/memory_form.html'

    def get(self, request):
        form = MemoryForm(user=request.user)
        return render(request, self.template_name, {'form': form, 'action': 'Create'})

    def post(self, request):
        form = MemoryForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                service = MemoryService()
                memory = service.create_memory(
                    user=request.user,
                    title=form.cleaned_data['title'],
                    content=form.cleaned_data['content'],
                    memory_type=form.cleaned_data['memory_type'],
                    tags=form.cleaned_data['tags'],
                    scope=form.cleaned_data['scope'],
                )
                messages.success(request, f"Memory '{memory.title}' created.")
                return redirect('memory_detail', pk=memory.pk)
            except PermissionError as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'action': 'Create'})


class MemoryUpdateView(LoginRequiredMixin, View):
    template_name = 'memories/memory_form.html'

    def _get_memory(self, request, pk):
        service = MemoryService()
        memory = service.get_memory(pk, request.user)
        if not memory:
            messages.error(request, "Memory not found or access denied.")
            return None, service
        # Check edit permission
        if memory.scope == Memory.SCOPE_ORGANIZATION and not request.user.is_staff:
            messages.error(request, "Only admins can edit organization memories.")
            return None, service
        if memory.scope == Memory.SCOPE_USER and memory.created_by != request.user:
            messages.error(request, "You can only edit your own memories.")
            return None, service
        return memory, service

    def get(self, request, pk):
        memory, _ = self._get_memory(request, pk)
        if not memory:
            return redirect('memory_list')
        # Render tags as JSON string for the form
        initial = {'tags': json.dumps(memory.tags) if memory.tags else '[]'}
        form = MemoryForm(instance=memory, user=request.user, initial=initial)
        return render(request, self.template_name, {'form': form, 'memory': memory, 'action': 'Edit'})

    def post(self, request, pk):
        memory, service = self._get_memory(request, pk)
        if not memory:
            return redirect('memory_list')
        form = MemoryForm(request.POST, instance=memory, user=request.user)
        if form.is_valid():
            try:
                service.update_memory(
                    memory.pk, request.user,
                    title=form.cleaned_data['title'],
                    content=form.cleaned_data['content'],
                    memory_type=form.cleaned_data['memory_type'],
                    tags=form.cleaned_data['tags'],
                    scope=form.cleaned_data['scope'],
                )
                messages.success(request, "Memory updated.")
                return redirect('memory_detail', pk=memory.pk)
            except PermissionError as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'memory': memory, 'action': 'Edit'})


class MemoryDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        try:
            service = MemoryService()
            service.delete_memory(pk, request.user)
            messages.success(request, "Memory deleted.")
        except (PermissionError, ValueError) as e:
            messages.error(request, str(e))
        return redirect('memory_list')


class MemoryImportView(LoginRequiredMixin, View):
    template_name = 'memories/memory_import.html'

    def get(self, request):
        form = MemoryImportForm(user=request.user)
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = MemoryImportForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                service = MemoryService()
                memory = service.import_document(
                    user=request.user,
                    title=form.cleaned_data['title'],
                    content=form.cleaned_data['content'],
                    tags=form.cleaned_data['tags'],
                    scope=form.cleaned_data['scope'],
                )
                messages.success(request, f"Document '{memory.title}' imported and indexed.")
                return redirect('memory_detail', pk=memory.pk)
            except PermissionError as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form})


class MemorySearchAPIView(LoginRequiredMixin, View):
    def get(self, request):
        query = request.GET.get('q', '').strip()
        limit = min(int(request.GET.get('limit', 5)), 20)
        if not query:
            return JsonResponse({'results': []})
        service = MemoryService()
        results = service.search_memories(query, request.user, limit=limit)
        return JsonResponse({'results': results})

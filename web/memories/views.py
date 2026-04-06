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


# ---------------------------------------------------------------------------
# Interview Wizard
# ---------------------------------------------------------------------------

INTERVIEW_STEPS = [
    {
        'key': 'identity',
        'title': 'Identity',
        'description': 'Capture who you are at a fundamental level — beyond job titles.',
        'questions': [
            ('Name & Role', "What's your name and what's your current role or title?"),
            ('Organization', "What organization or company are you with, if any?"),
            ('What You Actually Do', "If you had to explain what you actually do to someone at a dinner party — not your title, but what you actually spend your time on — what would you say?"),
            ('Your Reputation', "What do people come to you for? What's the thing where someone says 'you should talk to [you] about that'?"),
        ],
        'tags': ['personal-context', 'identity'],
    },
    {
        'key': 'role',
        'title': 'Role & Responsibilities',
        'description': 'Capture the operational reality of your work week.',
        'questions': [
            ('Typical Week', "Walk me through a typical week. What are the recurring things that happen every week without fail?"),
            ('Accountability', "What are you directly accountable for — what are the things where if they don't happen, it's on you?"),
            ('Regular Decisions', "What decisions do you make regularly? Not the big strategic ones — the routine ones that come up every week."),
            ('Outputs', "What do you produce? Reports, analyses, plans, code, presentations — what are the actual outputs of your work?"),
            ('Reporting Structure', "Who do you report to? Who reports to you, if anyone?"),
            ('Quarterly Rhythms', "Are there monthly or quarterly rhythms that shape your work — planning cycles, reviews, board meetings?"),
        ],
        'tags': ['personal-context', 'role'],
    },
    {
        'key': 'projects',
        'title': 'Current Projects',
        'description': 'Document your active workstreams, priorities, and blockers.',
        'questions': [
            ('Active Work', "What are you actively working on right now? List them out — project names or short descriptions."),
            ('Status & Done', "For each project: what is it, where does it stand, and what does done look like?"),
            ('Collaborators', "Who are you working with on each project?"),
            ('Priority Order', "If you had to rank these by priority right now, how would they stack up?"),
            ('Blockers', "Is anything stalled or blocked? What's the situation there?"),
        ],
        'tags': ['personal-context', 'projects'],
    },
    {
        'key': 'team',
        'title': 'Team & Relationships',
        'description': 'Map the people you work with and how to work well with them.',
        'questions': [
            ('Key People', "Who are the 5–8 people you interact with most in your work? Give names and roles."),
            ('Working Dynamics', "What's your working relationship with each? How do you typically interact — meetings, Slack, email?"),
            ('Mutual Needs', "What does each person need from you, and what do you need from them?"),
            ('AI Context', "Is there anything an AI working on your behalf should know about working with or preparing for interactions with any of them?"),
        ],
        'tags': ['personal-context', 'team'],
    },
    {
        'key': 'tools',
        'title': 'Tools & Systems',
        'description': 'Document your technology stack, configurations, and data locations.',
        'questions': [
            ('Daily Stack', "What tools and platforms do you use every day? Walk through your core stack."),
            ('Customizations', "How is your setup customized? Any specific configurations, integrations, or workflows an agent should know about?"),
            ('Where Data Lives', "Where does your important data live — docs, spreadsheets, databases, specific platforms?"),
            ('Under Evaluation', "Are there tools you're currently evaluating or planning to start using?"),
            ('Deliberately Stopped', "Anything you've tried and deliberately stopped using? What didn't work?"),
        ],
        'tags': ['personal-context', 'tools'],
    },
    {
        'key': 'communication',
        'title': 'Communication Style',
        'description': 'Capture your voice so AI can write like you, not like a template.',
        'questions': [
            ('Length & Detail', "When you write an email or a message, are you generally brief and to the point, or do you tend to give more context and detail?"),
            ('Formality', "How formal is your writing at work? Does it shift depending on who you're writing to?"),
            ("Doesn't Sound Like You", "What bothers you when you read something written for you or on your behalf? What makes you think 'that doesn't sound like me'?"),
            ('Your Phrases', "Are there specific words, phrases, or patterns you know you use a lot? Things people would recognize as your voice?"),
            ('Phrases You Avoid', "Are there words or phrases you actively avoid? Things that sound fake, corporate, or just not you?"),
            ('Email Structure', "How do you typically structure an email — do you lead with the ask, give background first, use bullet points, write in paragraphs?"),
        ],
        'tags': ['personal-context', 'communication'],
    },
    {
        'key': 'goals',
        'title': 'Goals & Priorities',
        'description': "Articulate what you're optimizing for and what tradeoffs you make.",
        'questions': [
            ('Near-term Success', "What are you trying to accomplish in the next few months? What does success look like by quarter's end?"),
            ('Longer Arc', "What are you building toward over the next year or couple of years?"),
            ('Tradeoff Preferences', "When you have to make a tradeoff — speed vs. quality, short-term vs. long-term, growth vs. stability — where do you generally land?"),
            ('Deliberately Deprioritized', "What important work are you explicitly putting aside right now and why?"),
            ('Six-Month Vision', "If things go well over the next six months, what's different about your work or your life?"),
        ],
        'tags': ['personal-context', 'goals'],
    },
    {
        'key': 'preferences',
        'title': 'Preferences & Constraints',
        'description': 'Set the hard rules and boundaries for how you work.',
        'questions': [
            ('Time & Availability', "Are there hard constraints on your time or availability that any agent working for you should know? Time zones, hours you don't work, days that are off limits?"),
            ('Non-negotiables', "What are your non-negotiables — things you insist on in how your work gets done, outputs get formatted, or interactions happen?"),
            ('Things You Hate', "What do you hate? Meetings that should be emails, specific jargon, output formats that annoy you — anything where your reaction is strong."),
            ('Personal Constraints', "Are there personal constraints that affect your work — travel limitations, family schedule considerations, health factors — anything you'd want an agent to account for?"),
            ('AI Output Preferences', "When an AI produces something for you, what are your formatting preferences? Length, structure, level of detail, tone?"),
        ],
        'tags': ['personal-context', 'preferences'],
    },
    {
        'key': 'domain',
        'title': 'Domain Knowledge',
        'description': 'Map your expertise so AI uses your vocabulary correctly.',
        'questions': [
            ('Deep Expertise', "What do you know deeply enough to teach someone else?"),
            ('Your Vocabulary', "What terms do you use daily that a general AI might misdefine or over-explain?"),
            ('Industry Rules', "What invisible industry rules, regulations, or market realities shape everything you do?"),
            ('Thinking Frameworks', "What thinking tools or problem-solving approaches do you rely on regularly?"),
            ('Still Learning', "Where are you still developing knowledge and would prefer more thorough explanation?"),
        ],
        'tags': ['personal-context', 'domain'],
    },
    {
        'key': 'decisions',
        'title': 'Decision Making',
        'description': 'Capture how you think so AI can reason with you, not just for you.',
        'questions': [
            ('Decision Approach', "How do you generally make decisions? Are you the type to analyze everything, go with your gut, talk it through with people, sleep on it?"),
            ('Information Needs', "What information do you want before you make a call? What makes you feel ready to decide?"),
            ('Recent Example', "Tell me about a significant decision you've made recently. What was it and how did you think it through?"),
            ('Another Example', "Can you give me another example — ideally a different kind of decision?"),
            ('Incomplete Info', "How do you handle situations where you don't have enough information but still need to decide?"),
            ('Current Decision', "Is there a decision you're currently sitting with or working through?"),
        ],
        'tags': ['personal-context', 'decisions'],
    },
]


def _build_memory_content(step: dict, response: str) -> str:
    """Format a step's questions + user response as structured markdown."""
    lines = [f"# {step['title']}", '']
    for label, question in step['questions']:
        lines.append(f"## {label}")
        lines.append(question)
        lines.append('')
    lines += ['---', '', '## Your Response', '', response.strip()]
    return '\n'.join(lines)


class MemoryInterviewView(LoginRequiredMixin, View):
    template_name = 'memories/interview_wizard.html'

    def get(self, request):
        return render(request, self.template_name, {'steps': INTERVIEW_STEPS})

    def post(self, request):
        service = MemoryService()

        # Delete any existing personal-context memories for this user
        existing = Memory.objects.filter(
            created_by=request.user,
            tags__contains=['personal-context'],
            is_active=True,
        )
        for mem in existing:
            try:
                service.delete_memory(mem.pk, request.user)
            except Exception:
                pass

        created = 0
        for step in INTERVIEW_STEPS:
            response = request.POST.get(f"response_{step['key']}", '').strip()
            if not response:
                continue
            content = _build_memory_content(step, response)
            try:
                service.import_document(
                    user=request.user,
                    title=f"Personal Context: {step['title']}",
                    content=content,
                    tags=step['tags'],
                    scope=Memory.SCOPE_USER,
                )
                created += 1
            except Exception as e:
                logger.error(f"Interview wizard: failed to create memory for {step['key']}: {e}")

        if created:
            messages.success(request, f"Interview complete — {created} personal context memor{'y' if created == 1 else 'ies'} created.")
        else:
            messages.warning(request, "No responses were provided — no memories created.")
        return redirect('memory_list')

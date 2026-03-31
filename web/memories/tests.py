"""
Tests for the Memories feature.

Covers:
1. Model: create, unique_together, to_dict
2. MemoryService: CRUD, permissions, tag matching
3. MCP tools: memories_list, memories_get, memories_create, memories_delete, memories_import
4. Auto-injection: _get_injected_memories tag matching + <system_memory> wrapping
5. Views: list, detail, create, update, delete, import
"""

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import Memory, MemoryUsage
from .services import MemoryService, _split_content

User = get_user_model()


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class MemoryModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pass')

    def test_create_user_memory(self):
        m = Memory.objects.create(
            title='Test convention',
            content='We use pytest-django',
            scope=Memory.SCOPE_USER,
            created_by=self.user,
        )
        self.assertEqual(m.memory_type, Memory.TYPE_TEXT)
        self.assertEqual(m.scope, Memory.SCOPE_USER)
        self.assertEqual(m.usage_count, 0)

    def test_to_dict(self):
        m = Memory.objects.create(
            title='T', content='C', scope=Memory.SCOPE_USER, created_by=self.user, tags=['django']
        )
        d = m.to_dict()
        self.assertEqual(d['title'], 'T')
        self.assertEqual(d['tags'], ['django'])

    def test_increment_usage(self):
        m = Memory.objects.create(title='T', content='C', created_by=self.user)
        m.increment_usage()
        m.refresh_from_db()
        self.assertEqual(m.usage_count, 1)

    def test_unique_together(self):
        Memory.objects.create(title='Dup', content='X', scope=Memory.SCOPE_USER, created_by=self.user)
        with self.assertRaises(Exception):
            Memory.objects.create(title='Dup', content='Y', scope=Memory.SCOPE_USER, created_by=self.user)


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

class MemoryServiceTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass', is_staff=True)
        self.user = User.objects.create_user(username='bob', password='pass')
        self.other = User.objects.create_user(username='carol', password='pass')
        self.service = MemoryService()

    def test_create_user_memory(self):
        m = self.service.create_memory(self.user, 'Fact', 'Content', tags=['python'])
        self.assertEqual(m.scope, Memory.SCOPE_USER)
        self.assertEqual(m.created_by, self.user)

    def test_create_org_memory_requires_staff(self):
        with self.assertRaises(PermissionError):
            self.service.create_memory(self.user, 'Shared', 'Content', scope=Memory.SCOPE_ORGANIZATION)

    def test_create_org_memory_as_admin(self):
        m = self.service.create_memory(self.admin, 'Shared', 'Content', scope=Memory.SCOPE_ORGANIZATION)
        self.assertEqual(m.scope, Memory.SCOPE_ORGANIZATION)

    def test_list_includes_org_and_own(self):
        org_m = self.service.create_memory(self.admin, 'Org fact', 'Org content', scope=Memory.SCOPE_ORGANIZATION)
        user_m = self.service.create_memory(self.user, 'My fact', 'My content')
        other_m = self.service.create_memory(self.other, 'Other fact', 'Other content')

        visible = self.service.list_memories(self.user)
        ids = [m.pk for m in visible]
        self.assertIn(org_m.pk, ids)      # org visible to all
        self.assertIn(user_m.pk, ids)     # user's own
        self.assertNotIn(other_m.pk, ids) # other user's personal not visible

    def test_delete_own_memory(self):
        m = self.service.create_memory(self.user, 'Del me', 'x')
        self.service.delete_memory(m.pk, self.user)
        m.refresh_from_db()
        self.assertFalse(m.is_active)

    def test_delete_others_memory_denied(self):
        m = self.service.create_memory(self.user, 'Mine', 'x')
        with self.assertRaises(PermissionError):
            self.service.delete_memory(m.pk, self.other)

    def test_update_own_memory(self):
        m = self.service.create_memory(self.user, 'Old title', 'Content')
        self.service.update_memory(m.pk, self.user, title='New title')
        m.refresh_from_db()
        self.assertEqual(m.title, 'New title')

    def test_update_org_memory_requires_admin(self):
        m = self.service.create_memory(self.admin, 'Org', 'Content', scope=Memory.SCOPE_ORGANIZATION)
        with self.assertRaises(PermissionError):
            self.service.update_memory(m.pk, self.user, title='Modified')

    def test_get_memories_by_tags(self):
        m1 = self.service.create_memory(self.user, 'M1', 'Content 1', tags=['django', 'testing'])
        m2 = self.service.create_memory(self.user, 'M2', 'Content 2', tags=['react'])
        m3 = self.service.create_memory(self.admin, 'M3', 'Content 3', scope=Memory.SCOPE_ORGANIZATION, tags=['django'])

        results = self.service.get_memories_by_tags(['django'], self.user)
        ids = [m.pk for m in results]
        self.assertIn(m1.pk, ids)
        self.assertIn(m3.pk, ids)
        self.assertNotIn(m2.pk, ids)

    def test_get_memories_by_tags_empty(self):
        results = self.service.get_memories_by_tags([], self.user)
        self.assertEqual(results, [])

    def test_import_document(self):
        m = self.service.import_document(self.user, 'Guide', 'Long content...' * 10, tags=['guide'])
        self.assertEqual(m.memory_type, Memory.TYPE_DOCUMENT)

    def test_import_document_org_requires_admin(self):
        with self.assertRaises(PermissionError):
            self.service.import_document(self.user, 'Guide', 'Content', scope=Memory.SCOPE_ORGANIZATION)

    def test_fallback_text_search(self):
        self.service.create_memory(self.user, 'React testing', 'Use React Testing Library for component tests')
        results = self.service._fallback_text_search('component tests', self.user, limit=5)
        self.assertTrue(len(results) > 0)


# ---------------------------------------------------------------------------
# _split_content utility
# ---------------------------------------------------------------------------

class SplitContentTest(TestCase):
    def test_short_content_not_split(self):
        chunks = _split_content('Short content', 2000)
        self.assertEqual(len(chunks), 1)

    def test_long_content_split(self):
        content = '\n\n'.join(['Paragraph ' + str(i) for i in range(50)])
        chunks = _split_content(content, 100)
        self.assertGreater(len(chunks), 1)
        # All content should be preserved
        rejoined = '\n\n'.join(chunks)
        self.assertIn('Paragraph 0', rejoined)
        self.assertIn('Paragraph 49', rejoined)


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------

class MemoriesMCPToolsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass', is_staff=True)
        self.user = User.objects.create_user(username='bob', password='pass')
        self.service = MemoryService()

    def test_memories_list_tool(self):
        from mcp_server.tools import memories_list
        self.service.create_memory(self.user, 'Fact', 'Content', tags=['django'])
        result = memories_list(user=self.user)
        self.assertIn('Fact', result)

    def test_memories_list_empty(self):
        from mcp_server.tools import memories_list
        result = memories_list(user=self.user)
        self.assertIn('No memories found', result)

    def test_memories_get_tool(self):
        from mcp_server.tools import memories_get
        m = self.service.create_memory(self.user, 'Detail test', 'Full content here')
        result = memories_get(memory_id=m.pk, user=self.user)
        self.assertIn('Detail test', result)
        self.assertIn('Full content here', result)

    def test_memories_get_not_found(self):
        from mcp_server.tools import memories_get
        result = memories_get(memory_id=99999, user=self.user)
        self.assertIn('not found', result.lower())

    def test_memories_create_tool(self):
        from mcp_server.tools import memories_create
        result = memories_create(title='New fact', content='Some content', user=self.user)
        self.assertIn('created', result.lower())
        self.assertTrue(Memory.objects.filter(title='New fact', created_by=self.user).exists())

    def test_memories_create_org_denied_for_regular_user(self):
        from mcp_server.tools import memories_create, ToolError
        with self.assertRaises(ToolError):
            memories_create(title='Org', content='Content', scope='organization', user=self.user)

    def test_memories_create_org_allowed_for_admin(self):
        from mcp_server.tools import memories_create
        result = memories_create(title='Org fact', content='Content', scope='organization', user=self.admin)
        self.assertIn('created', result.lower())

    def test_memories_delete_tool(self):
        from mcp_server.tools import memories_delete
        m = self.service.create_memory(self.user, 'Del me', 'x')
        result = memories_delete(memory_id=m.pk, user=self.user)
        self.assertIn('deleted', result.lower())

    def test_memories_import_tool_personal(self):
        from mcp_server.tools import memories_import
        result = memories_import(title='My Guide', content='## Section\nContent here', user=self.user)
        self.assertIn('imported', result.lower())

    def test_memories_import_tool_org_denied(self):
        from mcp_server.tools import memories_import, ToolError
        with self.assertRaises(ToolError):
            memories_import(title='Org Guide', content='Content', scope='organization', user=self.user)

    def test_memories_import_tool_org_allowed_for_admin(self):
        from mcp_server.tools import memories_import
        result = memories_import(title='Org Doc', content='Content', scope='organization', user=self.admin)
        self.assertIn('imported', result.lower())


# ---------------------------------------------------------------------------
# Auto-injection tests
# ---------------------------------------------------------------------------

class AutoInjectionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='inject_user', password='pass')
        self.service = MemoryService()

    def test_injection_matches_tag_in_args(self):
        from mcp_server.streamable import _get_injected_memories
        self.service.create_memory(self.user, 'Django tips', 'Use class-based views', tags=['django'])
        result = _get_injected_memories({'query': 'django orm'}, self.user)
        self.assertIn('<system_memory>', result)
        self.assertIn('Django tips', result)
        self.assertIn('</system_memory>', result)

    def test_no_injection_when_no_tag_match(self):
        from mcp_server.streamable import _get_injected_memories
        self.service.create_memory(self.user, 'React tips', 'Use hooks', tags=['react'])
        result = _get_injected_memories({'query': 'python testing'}, self.user)
        self.assertEqual(result, '')

    def test_no_injection_on_empty_args(self):
        from mcp_server.streamable import _get_injected_memories
        result = _get_injected_memories({}, self.user)
        self.assertEqual(result, '')

    def test_injection_from_list_arg(self):
        from mcp_server.streamable import _get_injected_memories
        self.service.create_memory(self.user, 'Testing tips', 'Use fixtures', tags=['testing'])
        result = _get_injected_memories({'tags': ['testing', 'python']}, self.user)
        self.assertIn('<system_memory>', result)

    def test_system_memory_structure(self):
        from mcp_server.streamable import _get_injected_memories
        self.service.create_memory(self.user, 'My tip', 'Tip content', tags=['mytag'])
        result = _get_injected_memories({'topic': 'mytag'}, self.user)
        self.assertTrue(result.startswith('<system_memory>'))
        self.assertTrue(result.strip().endswith('</system_memory>'))
        self.assertIn('[My tip]', result)
        self.assertIn('Tip content', result)

    def test_org_memory_injected_for_any_user(self):
        from mcp_server.streamable import _get_injected_memories
        admin = User.objects.create_user(username='admin2', password='pass', is_staff=True)
        other = User.objects.create_user(username='other2', password='pass')
        self.service.create_memory(admin, 'Org tip', 'Org content', scope=Memory.SCOPE_ORGANIZATION, tags=['shared'])
        result = _get_injected_memories({'q': 'shared'}, other)
        self.assertIn('<system_memory>', result)
        self.assertIn('Org tip', result)


# ---------------------------------------------------------------------------
# View tests
# ---------------------------------------------------------------------------

class MemoryViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin_view', password='pass', is_staff=True)
        self.user = User.objects.create_user(username='user_view', password='pass')
        self.service = MemoryService()

    def test_list_requires_login(self):
        resp = self.client.get(reverse('memory_list'))
        self.assertEqual(resp.status_code, 302)

    def test_list_authenticated(self):
        self.client.login(username='user_view', password='pass')
        resp = self.client.get(reverse('memory_list'))
        self.assertEqual(resp.status_code, 200)

    def test_create_get(self):
        self.client.login(username='user_view', password='pass')
        resp = self.client.get(reverse('memory_create'))
        self.assertEqual(resp.status_code, 200)

    def test_create_post(self):
        self.client.login(username='user_view', password='pass')
        resp = self.client.post(reverse('memory_create'), {
            'title': 'View test memory',
            'content': 'Test content',
            'memory_type': 'text',
            'tags': '["testing"]',
            'scope': 'user',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Memory.objects.filter(title='View test memory').exists())

    def test_detail_own_memory(self):
        self.client.login(username='user_view', password='pass')
        m = self.service.create_memory(self.user, 'My detail', 'Content')
        resp = self.client.get(reverse('memory_detail', args=[m.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_other_user_personal_redirects(self):
        self.client.login(username='user_view', password='pass')
        other = User.objects.create_user(username='other_view', password='pass')
        m = self.service.create_memory(other, 'Private', 'Secret')
        resp = self.client.get(reverse('memory_detail', args=[m.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_delete_own_memory(self):
        self.client.login(username='user_view', password='pass')
        m = self.service.create_memory(self.user, 'Delete me', 'Content')
        resp = self.client.post(reverse('memory_delete', args=[m.pk]))
        self.assertEqual(resp.status_code, 302)
        m.refresh_from_db()
        self.assertFalse(m.is_active)

    def test_import_get(self):
        self.client.login(username='user_view', password='pass')
        resp = self.client.get(reverse('memory_import'))
        self.assertEqual(resp.status_code, 200)

    def test_import_personal_as_regular_user(self):
        self.client.login(username='user_view', password='pass')
        resp = self.client.post(reverse('memory_import'), {
            'title': 'My guide',
            'content': '## Guide\nContent here',
            'tags': '["guide"]',
            'scope': 'user',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Memory.objects.filter(title='My guide', memory_type='document').exists())

    def test_create_org_memory_denied_for_regular_user(self):
        self.client.login(username='user_view', password='pass')
        resp = self.client.post(reverse('memory_create'), {
            'title': 'Org attempt',
            'content': 'Content',
            'memory_type': 'text',
            'tags': '[]',
            'scope': 'organization',
        })
        # Should stay on form (re-render with error), not create the memory
        self.assertFalse(Memory.objects.filter(title='Org attempt').exists())

    def test_create_org_memory_allowed_for_admin(self):
        self.client.login(username='admin_view', password='pass')
        resp = self.client.post(reverse('memory_create'), {
            'title': 'Admin org memory',
            'content': 'Content',
            'memory_type': 'text',
            'tags': '["org"]',
            'scope': 'organization',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Memory.objects.filter(title='Admin org memory', scope='organization').exists())

    def test_search_api(self):
        self.client.login(username='user_view', password='pass')
        self.service.create_memory(self.user, 'Searchable', 'Content to find')
        resp = self.client.get(reverse('memory_search_api'), {'q': 'Searchable'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('results', data)

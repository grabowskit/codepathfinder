"""
Test script for Phase 2: Project-Scoped Search Implementation
Run with: docker-compose exec web python manage.py shell < mcp_server/test_project_scoping.py
"""

from django.contrib.auth import get_user_model
from projects.models import PathfinderProject
from mcp_server.tools import resolve_project_indices, ToolError

User = get_user_model()

print("="*80)
print("Phase 2 Test: Project-Scoped Search")
print("="*80)

# Setup: Create test users and projects
print("\n1. Setting up test data...")

# Create users
user1, _ = User.objects.get_or_create(username='alice', defaults={'email': 'alice@test.com'})
user2, _ = User.objects.get_or_create(username='bob', defaults={'email': 'bob@test.com'})

# Create projects
project_a = PathfinderProject.objects.create(
    user=user1,
    name='Project Alpha',
    repository_url='https://github.com/test/alpha.git'
)

project_b = PathfinderProject.objects.create(
    user=user1,
    name='Project Beta',
    repository_url='https://github.com/test/beta.git'
)

project_c = PathfinderProject.objects.create(
    user=user2,
    name='Project Charlie',
    repository_url='https://github.com/test/charlie.git'
)

# Share project_b with user2
project_b.shared_with.add(user2)

print(f"   Created project {project_a.name} (ID: {project_a.id}, Index: {project_a.custom_index_name}, Owner: {user1.username})")
print(f"   Created project {project_b.name} (ID: {project_b.id}, Index: {project_b.custom_index_name}, Owner: {user1.username}, Shared with: {user2.username})")
print(f"   Created project {project_c.name} (ID: {project_c.id}, Index: {project_c.custom_index_name}, Owner: {user2.username})")

# Test 1: Resolve specific projects user owns
print("\n2. Test: User1 searches their own project (Project Alpha)")
try:
    result = resolve_project_indices(user1, projects=['Project Alpha'])
    print(f"   ✓ Resolved to: {result}")
    assert result == project_a.custom_index_name
except Exception as e:
    print(f"   ✗ FAILED: {e}")

# Test 2: Resolve multiple projects
print("\n3. Test: User1 searches multiple projects (Alpha + Beta)")
try:
    result = resolve_project_indices(user1, projects=['Project Alpha', 'Project Beta'])
    expected = f"{project_a.custom_index_name},{project_b.custom_index_name}"
    print(f"   ✓ Resolved to: {result}")
    # Order might differ, so check both indices are present
    assert project_a.custom_index_name in result
    assert project_b.custom_index_name in result
except Exception as e:
    print(f"   ✗ FAILED: {e}")

# Test 3: Resolve shared project
print("\n4. Test: User2 searches shared project (Project Beta)")
try:
    result = resolve_project_indices(user2, projects=['Project Beta'])
    print(f"   ✓ Resolved to: {result}")
    assert result == project_b.custom_index_name
except Exception as e:
    print(f"   ✗ FAILED: {e}")

# Test 4: Access denied - user tries to access project they don't own
print("\n5. Test: User2 tries to access Project Alpha (should fail)")
try:
    result = resolve_project_indices(user2, projects=['Project Alpha'])
    print(f"   ✗ FAILED: Should have raised ToolError, got: {result}")
except ToolError as e:
    print(f"   ✓ Correctly denied access: {e}")
except Exception as e:
    print(f"   ✗ FAILED with wrong exception: {e}")

# Test 5: Default behavior - search all accessible projects
print("\n6. Test: User1 searches without specifying projects (default: all accessible)")
try:
    result = resolve_project_indices(user1, projects=None)
    print(f"   ✓ Resolved to: {result}")
    # User1 owns Alpha and Beta
    assert project_a.custom_index_name in result
    assert project_b.custom_index_name in result
    assert project_c.custom_index_name not in result  # Doesn't own Charlie
except Exception as e:
    print(f"   ✗ FAILED: {e}")

# Test 6: User2 default search (owns Charlie, has access to Beta)
print("\n7. Test: User2 searches without specifying projects")
try:
    result = resolve_project_indices(user2, projects=None)
    print(f"   ✓ Resolved to: {result}")
    assert project_b.custom_index_name in result  # Shared
    assert project_c.custom_index_name in result  # Owns
    assert project_a.custom_index_name not in result  # No access
except Exception as e:
    print(f"   ✗ FAILED: {e}")

# Test 7: Explicit index override (superuser case)
print("\n8. Test: Explicit index override (bypasses project resolution)")
try:
    result = resolve_project_indices(user1, projects=['Project Alpha'], index='custom-override-index')
    print(f"   ✓ Override successful: {result}")
    assert result == 'custom-override-index'
except Exception as e:
    print(f"   ✗ FAILED: {e}")

# Test 8: Non-existent project
print("\n9. Test: Search for non-existent project (should fail)")
try:
    result = resolve_project_indices(user1, projects=['NonExistent Project'])
    print(f"   ✗ FAILED: Should have raised ToolError, got: {result}")
except ToolError as e:
    print(f"   ✓ Correctly rejected: {e}")
except Exception as e:
    print(f"   ✗ FAILED with wrong exception: {e}")

# Test 9: Unauthenticated user with projects parameter
print("\n10. Test: Unauthenticated user tries to search specific project (should fail)")
try:
    result = resolve_project_indices(None, projects=['Project Alpha'])
    print(f"   ✗ FAILED: Should have raised ToolError, got: {result}")
except ToolError as e:
    print(f"   ✓ Correctly denied: {e}")
except Exception as e:
    print(f"   ✗ FAILED with wrong exception: {e}")

# Cleanup
print("\n11. Cleaning up test data...")
PathfinderProject.objects.filter(
    id__in=[project_a.id, project_b.id, project_c.id]
).delete()
User.objects.filter(username__in=['alice', 'bob']).delete()
print("   ✓ Test data cleaned up")

print("\n" + "="*80)
print("Phase 2 Tests Complete!")
print("="*80)

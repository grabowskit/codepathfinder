# Claude Desktop Integration Testing Guide

## Overview

This guide will help you test the newly deployed MCP project-scoped search feature with Claude Desktop.

## Pre-Test Checklist

- ✅ Backend deployed with OAuth support
- ✅ MCP endpoint accessible at `http://localhost:8000/mcp`
- ✅ OAuth authorization flow working
- ✅ All projects have custom index names
- ✅ All pods healthy and responding

## Configuration

### Connection Method: OAuth (Recommended)

Claude Desktop now fully supports OAuth authentication with CodePathfinder's MCP server.

## Testing Steps

### Step 1: Configure Claude Desktop with OAuth

1. Open **Claude Desktop**
2. Go to **Settings** (gear icon) → **Connectors**
3. Click **Add Connector** → **Custom**
4. Enter:
   - **Name:** `CodePathfinder`
   - **URL:** `http://localhost:8000/mcp`
5. Click **Add**
6. Your browser will open - log in to CodePathfinder
7. Click **Authorize** on the consent page
8. You'll be redirected back to Claude Desktop

### Alternative: API Key Configuration

If OAuth isn't available, use the MCP Bridge with an API key:

Add this to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "codepathfinder": {
      "command": "npx",
      "args": ["-y", "@grabowskit/mcp-bridge"],
      "env": {
        "CODEPATHFINDER_API_KEY": "YOUR_API_KEY",
        "CODEPATHFINDER_API_ENDPOINT": "http://localhost:8000/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

### Step 2: Verify Connection

For OAuth: Check that the connector shows as **Connected** in Settings → Connectors.

For API Key: Restart Claude Desktop after updating configuration:
1. Quit Claude Desktop completely
2. Restart Claude Desktop
3. Wait for MCP server connection to establish

### Step 3: Verify Connection

In a new Claude conversation, ask:
```
Can you list the available tools from CodePathfinder?
```

**Expected Response**: Claude should list 6 tools:
- semantic_code_search
- map_symbols_by_query
- size
- symbol_analysis
- read_file_from_chunks
- document_symbols

All tools should have a `projects` parameter in their schema.

### Step 4: Test Default Search (All Projects)

**Test Query**:
```
Search for authentication code in my projects
```

**Expected Behavior**:
- Claude calls `semantic_code_search(query="authentication code")`
- Backend searches all 3 projects (project-1, project-5, project-9 or similar)
- Results returned from all accessible projects

**Check**: Results should span multiple projects if authentication code exists in multiple places.

### Step 5: Test Specific Project Search

First, identify your project names:
```
What projects do I have indexed?
```

Then test with a specific project:
```
Search for [specific term] in the [project-name] project only
```

**Expected Behavior**:
- Claude calls `semantic_code_search(query="...", projects=["project-name"])`
- Backend validates user has access to that project
- Results only from that specific project

### Step 6: Test Multi-Project Search

```
Find API endpoints in the frontend and backend projects
```

**Expected Behavior**:
- Claude calls `semantic_code_search(query="API endpoints", projects=["frontend", "backend"])`
- Backend searches only those two projects
- Results from both projects, clearly labeled

### Step 7: Test Access Control

Try to search a project you don't own or aren't shared with:

```
Search for code in the [non-existent-project] project
```

**Expected Behavior**:
- Claude calls the tool with `projects=["non-existent-project"]`
- Backend returns error: "Projects not found or access denied: non-existent-project"
- Claude explains you don't have access to that project

### Step 8: Test Other Tools

Test the other 5 tools with project scoping:

**Map Symbols**:
```
Find all functions named 'authenticate' in my projects
```

**Size**:
```
How many documents are indexed in my backend project?
```

**Symbol Analysis**:
```
Analyze the 'login' function across all my projects
```

**Read File**:
```
Show me the contents of src/auth/login.ts from the backend project
```

**Document Symbols**:
```
What symbols in src/models/user.py need documentation?
```

## Monitoring During Tests

While testing, monitor the backend logs in a separate terminal:

```bash
kubectl logs -f codepathfinder-5bfcd8b7cd-s6275 -n codepathfinder -c web | grep -E "(SSE|tools/call|resolve_project_indices|ToolError)"
```

This will show:
- SSE connection establishment
- Tool calls with parameters
- Project resolution logic
- Any errors

## Expected Log Output

### Successful Connection
```
INFO SSE Connected: <session-id>
INFO Default search: User admin has 3 accessible project(s)
```

### Specific Project Search
```
INFO Resolved projects ['backend'] to indices: project-5
```

### Access Denied
```
WARNING Projects not found or access denied: non-existent-project
```

## Common Issues & Solutions

### Issue 1: "No tools available"

**Symptom**: Claude says it doesn't have access to CodePathfinder tools

**Solution**:
1. Check MCP server connection status in Claude Desktop settings
2. Verify OAuth authentication completed
3. Restart Claude Desktop
4. Check backend logs for authentication errors

### Issue 2: "Authentication failed"

**Symptom**: OAuth flow fails or returns 401 errors

**Solution**:
1. Verify you're logged into your CodePathfinder instance in your browser
2. Check that your account has projects
3. Verify OAuth app configuration (client_id matches)
4. Check backend logs for OAuth errors

### Issue 3: "No projects available"

**Symptom**: Backend returns error saying no projects available

**Solution**:
```bash
# Check if your user has projects
kubectl exec codepathfinder-5bfcd8b7cd-s6275 -n codepathfinder -c web -- python manage.py shell -c "
from projects.models import PathfinderProject
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.get(username='YOUR_USERNAME')  # Replace with your username
projects = PathfinderProject.objects.filter(user=user).values('id', 'name', 'custom_index_name')
for p in projects:
    print(p)
"
```

### Issue 4: "Search returns no results"

**Symptom**: Search completes but returns empty results

**Possible Causes**:
1. Projects not indexed yet (Elasticsearch indices empty)
2. Search query doesn't match indexed content
3. Elasticsearch connection issue

**Solution**:
1. Check if indices exist and have documents:
   ```
   Ask Claude: "How many documents are indexed in my projects?"
   ```
2. Try a broader search term
3. Check backend Elasticsearch connection logs

## Success Criteria

✅ **Test Passed If**:

1. All 6 tools visible in Claude Desktop
2. All tools have `projects` parameter in their schema
3. Default search (no projects specified) searches all accessible projects
4. Specific project search only searches that project
5. Multi-project search works correctly
6. Access control prevents unauthorized project access
7. No errors in backend logs
8. Search results are relevant and properly formatted

## Validation Checklist

After completing all tests:

- [ ] Connection established successfully
- [ ] All 6 tools available
- [ ] Default search works (all projects)
- [ ] Specific project search works
- [ ] Multi-project search works
- [ ] Access control working (errors for unauthorized projects)
- [ ] map_symbols_by_query tested
- [ ] size tested
- [ ] symbol_analysis tested
- [ ] read_file_from_chunks tested
- [ ] document_symbols tested
- [ ] No authentication errors
- [ ] No tool execution errors
- [ ] Results properly formatted

## Reporting Issues

If you encounter issues during testing:

1. **Capture Backend Logs**:
   ```bash
   kubectl logs codepathfinder-5bfcd8b7cd-s6275 -n codepathfinder -c web --tail=100 > test-logs.txt
   ```

2. **Note the Failure**:
   - What query did you run?
   - What was Claude's response?
   - What did you expect to happen?
   - What actually happened?

3. **Check Database State**:
   ```bash
   kubectl exec codepathfinder-5bfcd8b7cd-s6275 -n codepathfinder -c web -- python manage.py audit_project_indices
   ```

4. **Document the Issue**:
   - Add to GitHub Issues
   - Include logs, expected vs actual behavior
   - Note any error messages

## Next Steps After Testing

### If All Tests Pass

1. Mark integration testing as complete in [implementation summary](docs/mcp-project-scope-implementation-summary.md)
2. Monitor for 24 hours for any issues
3. Consider announcing the new feature to users
4. Update user documentation with project scoping examples

### If Tests Fail

1. Document failures with logs
2. Determine if rollback is needed
3. Fix issues in development
4. Re-deploy and re-test
5. Update deployment documentation with lessons learned

## Rollback Plan

If critical issues are found:

```bash
# Quick rollback
kubectl rollout undo deployment/codepathfinder -n codepathfinder
kubectl rollout status deployment/codepathfinder -n codepathfinder

# Verify rollback
kubectl get pods -n codepathfinder
```

See [Deployment Guide](docs/mcp-project-scope-deployment-guide.md) for full rollback procedure.

---

## Contact

For questions or issues:
- Deployment docs: [mcp-project-scope-deployment-guide.md](docs/mcp-project-scope-deployment-guide.md)
- Implementation summary: [mcp-project-scope-implementation-summary.md](docs/mcp-project-scope-implementation-summary.md)
- OAuth fixes: [mcp-oauth-fixes.md](docs/mcp-oauth-fixes.md)

---

**Testing Date**: _____________
**Tested By**: _____________
**Test Result**: ☐ Pass ☐ Fail
**Notes**: _____________

#!/usr/bin/env node

/**
 * CodePathfinder MCP Bridge
 *
 * This MCP server proxies tool calls to the CodePathfinder REST API.
 * It allows Claude Desktop to interact with CodePathfinder projects
 * using project-scoped API keys.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';

// Environment variables
const API_KEY = process.env.CODEPATHFINDER_API_KEY;
const API_ENDPOINT = process.env.CODEPATHFINDER_API_ENDPOINT || 'https://codepathfinder.com/api/v1/mcp/tools/call/';
const DISABLE_SSL_VERIFY = process.env.CODEPATHFINDER_DISABLE_SSL_VERIFY === 'true';

// Validate required environment variables
if (!API_KEY) {
  console.error('Error: CODEPATHFINDER_API_KEY environment variable is required');
  process.exit(1);
}

// Disable SSL verification for local development if requested
if (DISABLE_SSL_VERIFY) {
  console.error('WARNING: SSL certificate verification is DISABLED. Only use this for local development!');
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
}

// Tool definitions matching the Django backend
const TOOLS: Tool[] = [
  {
    name: 'semantic_code_search',
    description: 'Search code by semantic meaning using natural language queries. Searches all accessible projects by default, or specific projects if provided.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Natural language search query (e.g., "function that handles user authentication")',
        },
        projects: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of project names to search. If not provided, searches all accessible projects.',
        },
        index: {
          type: 'string',
          description: 'Optional index name override (advanced use only)',
        },
        size: {
          type: 'number',
          description: 'Maximum number of results to return (default: 10, max: 50)',
          default: 10,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'map_symbols_by_query',
    description: 'Find symbols (functions, classes, methods) matching a query, grouped by file path.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search query for symbol names (e.g., "authenticate", "UserController")',
        },
        projects: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of project names to search',
        },
        index: {
          type: 'string',
          description: 'Optional index name override (advanced use only)',
        },
        size: {
          type: 'number',
          description: 'Maximum number of files to return (default: 20)',
          default: 20,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'size',
    description: 'Get statistics about indexed projects (document count, storage size, segments).',
    inputSchema: {
      type: 'object',
      properties: {
        projects: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of project names to get stats for',
        },
        index: {
          type: 'string',
          description: 'Optional index name override (advanced use only)',
        },
      },
    },
  },
  {
    name: 'symbol_analysis',
    description: 'Analyze a symbol to find its definitions, call sites, and references across the codebase.',
    inputSchema: {
      type: 'object',
      properties: {
        symbol_name: {
          type: 'string',
          description: 'Name of the symbol to analyze (e.g., "authenticateUser", "UserModel")',
        },
        projects: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of project names to search',
        },
        index: {
          type: 'string',
          description: 'Optional index name override (advanced use only)',
        },
      },
      required: ['symbol_name'],
    },
  },
  {
    name: 'read_file_from_chunks',
    description: 'Reconstruct a complete file from indexed code chunks.',
    inputSchema: {
      type: 'object',
      properties: {
        file_path: {
          type: 'string',
          description: 'Path to the file to reconstruct (e.g., "src/auth/login.ts")',
        },
        projects: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of project names to search',
        },
        index: {
          type: 'string',
          description: 'Optional index name override (advanced use only)',
        },
      },
      required: ['file_path'],
    },
  },
  {
    name: 'document_symbols',
    description: 'List all symbols in a file that would benefit from documentation.',
    inputSchema: {
      type: 'object',
      properties: {
        file_path: {
          type: 'string',
          description: 'Path to the file to analyze (e.g., "src/models/user.ts")',
        },
        projects: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of project names to search',
        },
        index: {
          type: 'string',
          description: 'Optional index name override (advanced use only)',
        },
      },
      required: ['file_path'],
    },
  },
  // GitHub Tools
  {
    name: 'github_create_issue',
    description: 'Create a new GitHub issue on a project\'s repository.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Name of the project',
        },
        title: {
          type: 'string',
          description: 'Issue title',
        },
        body: {
          type: 'string',
          description: 'Issue body/description',
        },
        labels: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of label names',
        },
      },
      required: ['project_name', 'title', 'body'],
    },
  },
  {
    name: 'github_add_comment',
    description: 'Add a comment to a GitHub issue or pull request.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Name of the project',
        },
        issue_number: {
          type: 'number',
          description: 'Issue or PR number',
        },
        body: {
          type: 'string',
          description: 'Comment body',
        },
      },
      required: ['project_name', 'issue_number', 'body'],
    },
  },
  {
    name: 'github_create_pull_request',
    description: 'Create a new GitHub pull request.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Name of the project',
        },
        title: {
          type: 'string',
          description: 'PR title',
        },
        body: {
          type: 'string',
          description: 'PR body/description',
        },
        head: {
          type: 'string',
          description: 'Head branch name (source branch)',
        },
        base: {
          type: 'string',
          description: 'Base branch name (target branch, default: main)',
          default: 'main',
        },
      },
      required: ['project_name', 'title', 'body', 'head'],
    },
  },
  {
    name: 'github_create_branch',
    description: 'Create a new branch on a project\'s repository.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Name of the project',
        },
        branch_name: {
          type: 'string',
          description: 'Name for the new branch',
        },
        from_ref: {
          type: 'string',
          description: 'Source branch/ref to branch from (default: main)',
          default: 'main',
        },
      },
      required: ['project_name', 'branch_name'],
    },
  },
  {
    name: 'github_list_branches',
    description: 'List all branches in a project\'s repository.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Name of the project',
        },
      },
      required: ['project_name'],
    },
  },
  {
    name: 'github_get_repo_info',
    description: 'Get repository information for a project.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Name of the project',
        },
      },
      required: ['project_name'],
    },
  },
  // Skills Tools
  {
    name: 'skills_list',
    description: 'List all available skills with optional filtering by tags or curated status.',
    inputSchema: {
      type: 'object',
      properties: {
        tags: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of tags to filter by',
        },
        curated_only: {
          type: 'boolean',
          description: 'If true, only return curated skills',
          default: false,
        },
      },
    },
  },
  {
    name: 'skills_get',
    description: 'Get a skill by its exact name with full details and instructions.',
    inputSchema: {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          description: 'Exact name of the skill',
        },
      },
      required: ['name'],
    },
  },
  {
    name: 'skills_search',
    description: 'Search for skills by name, description, or tags.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search query string',
        },
        limit: {
          type: 'number',
          description: 'Maximum number of results (default: 5)',
          default: 5,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'skills_sync',
    description: 'Sync skills from the configured GitHub repository. Admin-only operation.',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'skills_import',
    description: 'Import a skill from SKILL.md formatted content with YAML frontmatter.',
    inputSchema: {
      type: 'object',
      properties: {
        content: {
          type: 'string',
          description: 'SKILL.md formatted content string with YAML frontmatter and markdown instructions',
        },
      },
      required: ['content'],
    },
  },
  {
    name: 'skills_activate',
    description: 'Activate a skill for the current conversation. Returns full instructions to follow as a persona.',
    inputSchema: {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          description: 'Exact name of the skill to activate (e.g., "code-review-coach")',
        },
      },
      required: ['name'],
    },
  },
];

/**
 * Proxy a tool call to the CodePathfinder API
 */
async function proxyToolCall(toolName: string, args: Record<string, unknown>): Promise<string> {
  try {
    const response = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${API_KEY}`,
      },
      body: JSON.stringify({
        name: toolName,
        arguments: args,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
      const errorMessage = (errorData as { error?: string }).error || `HTTP ${response.status}: ${response.statusText}`;
      throw new Error(`API error: ${errorMessage}`);
    }

    const data = await response.json() as { content: Array<{ type: string; text: string }> };

    // Extract text from MCP response format
    if (data.content && Array.isArray(data.content) && data.content.length > 0) {
      return data.content[0].text;
    }

    return 'No results returned from API';
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Failed to call CodePathfinder API: ${error.message}`);
    }
    throw new Error('Failed to call CodePathfinder API: Unknown error');
  }
}

/**
 * Main server setup
 */
async function main() {
  console.error('Starting CodePathfinder MCP Bridge...');
  console.error(`API Endpoint: ${API_ENDPOINT}`);
  console.error(`API Key: ${API_KEY?.substring(0, 15)}...`);

  const server = new Server(
    {
      name: 'codepathfinder-mcp-bridge',
      version: '1.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // Handle tool listing
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
      tools: TOOLS,
    };
  });

  // Handle tool calls
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name: toolName, arguments: args } = request.params;

    console.error(`Tool call: ${toolName}`);
    console.error(`Arguments: ${JSON.stringify(args, null, 2)}`);

    try {
      // Proxy the tool call to the Django API
      const result = await proxyToolCall(toolName, args as Record<string, unknown>);

      return {
        content: [
          {
            type: 'text',
            text: result,
          },
        ],
      };
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      console.error(`Error executing tool ${toolName}: ${errorMessage}`);

      return {
        content: [
          {
            type: 'text',
            text: `Error: ${errorMessage}`,
          },
        ],
        isError: true,
      };
    }
  });

  // Start the server
  const transport = new StdioServerTransport();
  await server.connect(transport);

  console.error('CodePathfinder MCP Bridge is running');
}

// Global error handlers to prevent crashing
process.on('uncaughtException', (error) => {
  console.error('Uncaught Exception:', error);
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('Unhandled Rejection at:', promise, 'reason:', reason);
});

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});

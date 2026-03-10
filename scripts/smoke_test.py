#!/usr/bin/env python
"""
CodePathfinder Smoke Test Runner

A CLI tool for running smoke tests to validate that all services
are running and responding correctly.

Usage:
    python scripts/smoke_test.py              # Run all tests
    python scripts/smoke_test.py --category health
    python scripts/smoke_test.py --category mcp
    python scripts/smoke_test.py -v --timing
    python scripts/smoke_test.py --output json

Options:
    --category    Test category: health, auth, projects, mcp, librechat, oauth, all
    --output      Output format: text, json, junit
    --base-url    Override base URL (default: https://localhost:8443)
    -v            Verbose output
    --timing      Show test durations
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

CATEGORIES = ['health', 'auth', 'projects', 'mcp', 'librechat', 'oauth']

# Find project root (parent of scripts directory)
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent


def print_banner():
    """Print the smoke test banner."""
    print("""
╔═══════════════════════════════════════════════════════════╗
║           CodePathfinder Smoke Test Suite                 ║
╚═══════════════════════════════════════════════════════════╝
""")


def main():
    parser = argparse.ArgumentParser(
        description='CodePathfinder Smoke Test Runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/smoke_test.py                    # Run all smoke tests
    python scripts/smoke_test.py --category health  # Run health checks only
    python scripts/smoke_test.py --category mcp -v  # Run MCP tests verbosely
    python scripts/smoke_test.py --output json      # Output as JSON
        """
    )

    parser.add_argument(
        '--category', '-c',
        choices=CATEGORIES + ['all'],
        default='all',
        help='Test category to run (default: all)'
    )

    parser.add_argument(
        '--output', '-o',
        choices=['text', 'json', 'junit'],
        default='text',
        help='Output format (default: text)'
    )

    parser.add_argument(
        '--base-url',
        default=os.getenv('SMOKE_TEST_BASE_URL', 'https://localhost:8443'),
        help='Base URL for tests (default: https://localhost:8443)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )

    parser.add_argument(
        '--timing',
        action='store_true',
        help='Show timing for each test'
    )

    parser.add_argument(
        '--failfast', '-x',
        action='store_true',
        help='Stop on first failure'
    )

    args = parser.parse_args()

    print_banner()

    # Build pytest command
    pytest_args = [
        sys.executable, '-m', 'pytest',
        str(PROJECT_ROOT / 'tests' / 'smoke'),
        '-m', 'smoke'
    ]

    # Filter by category
    if args.category != 'all':
        pytest_args.extend(['-k', args.category])
        print(f"Running category: {args.category}")
    else:
        print("Running all smoke tests")

    print(f"Base URL: {args.base_url}")
    print("-" * 60)

    # Verbosity
    if args.verbose:
        pytest_args.append('-v')
    else:
        pytest_args.append('-q')

    # Timing
    if args.timing:
        pytest_args.append('--durations=0')

    # Fail fast
    if args.failfast:
        pytest_args.append('-x')

    # Output format
    if args.output == 'json':
        json_file = PROJECT_ROOT / 'smoke_results.json'
        pytest_args.extend([
            '--json-report',
            f'--json-report-file={json_file}'
        ])
        print(f"JSON output: {json_file}")
    elif args.output == 'junit':
        junit_file = PROJECT_ROOT / 'smoke_results.xml'
        pytest_args.extend([f'--junitxml={junit_file}'])
        print(f"JUnit output: {junit_file}")

    # Set environment variables
    env = os.environ.copy()
    env['SMOKE_TEST_BASE_URL'] = args.base_url

    # Suppress warnings
    pytest_args.extend(['-W', 'ignore::DeprecationWarning'])

    print()

    # Run tests
    result = subprocess.run(pytest_args, env=env, cwd=str(PROJECT_ROOT))

    # Print summary
    print()
    print("=" * 60)
    if result.returncode == 0:
        print("STATUS: ALL SMOKE TESTS PASSING")
    else:
        print(f"STATUS: SOME TESTS FAILED (exit code: {result.returncode})")
    print("=" * 60)

    sys.exit(result.returncode)


if __name__ == '__main__':
    main()

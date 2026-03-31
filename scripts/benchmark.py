#!/usr/bin/env python3
"""
CodePathfinder Indexer Benchmark Tool

Measures indexing throughput in different environments to detect performance
regressions after indexer changes.

Usage:
    python scripts/benchmark.py --env local --username admin --password ...
    python scripts/benchmark.py --env production --username admin --password ...
    python scripts/benchmark.py --env local --env production  # compare both
    python scripts/benchmark.py --env local --runs 3 --note "after batch_size=20"

Scoring:
    score = (files_indexed / total_seconds) * 100
    Higher is better. Use the same --repo across runs for valid comparisons.

Cleanup:
    All created projects and Elasticsearch indices are deleted after each run,
    even if the run fails or is interrupted with Ctrl+C.
"""

import argparse
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
SCORES_FILE = PROJECT_ROOT / "benchmark_scores.md"

ENV_PRESETS = {
    "local": {
        "base_url": "https://localhost:8443",
        "verify_ssl": False,
        # Tiny repo: CPU-based ELSER is the bottleneck locally, so use a small
        # repo (~25 files) to keep runs under 5 minutes.
        "default_repo": "https://github.com/pallets/itsdangerous",
        "default_timeout": 1200,  # 20 min
    },
    "production": {
        "base_url": "https://codepathfinder.com",
        "verify_ssl": True,
        # Larger repo for production: K8s + Elastic Cloud ELSER handles it fast.
        "default_repo": "https://github.com/pallets/click",
        "default_timeout": 1800,  # 30 min
    },
}

POLL_INTERVAL = 10  # seconds between status polls
DEFAULT_TIMEOUT = 900  # 15 minutes fallback


def print_banner():
    print("""
╔═══════════════════════════════════════════════════════════╗
║         CodePathfinder Indexer Benchmark Tool             ║
╚═══════════════════════════════════════════════════════════╝
""")


def fmt_seconds(s):
    if s is None:
        return "n/a"
    if s < 60:
        return f"{s:.0f}s"
    return f"{s / 60:.1f}m"


class BenchmarkError(Exception):
    pass


class Benchmark:
    def __init__(self, base_url, verify_ssl, env_name, timeout):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.env_name = env_name
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.project_id = None
        self.project_name = None
        self._cleanup_done = False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, username, password):
        """Login via django-allauth session auth."""
        login_url = f"{self.base_url}/accounts/login/"

        # Fetch login page to get CSRF token
        resp = self.session.get(login_url, timeout=30)
        resp.raise_for_status()

        # CSRF cookie name is 'cpf_csrftoken' (settings.py CSRF_COOKIE_NAME)
        csrf = (
            self.session.cookies.get("cpf_csrftoken")
            or self.session.cookies.get("csrftoken")
            or self._extract_csrf_from_html(resp.text)
        )
        if not csrf:
            raise BenchmarkError("Could not find CSRF token on login page")

        payload = {
            "login": username,
            "password": password,
            "csrfmiddlewaretoken": csrf,
        }
        headers = {
            "Referer": login_url,
            "X-CSRFToken": csrf,
        }
        resp = self.session.post(login_url, data=payload, headers=headers, timeout=30, allow_redirects=True)

        # Allauth redirects to / on success; if we're still on the login page, auth failed
        if "/accounts/login/" in resp.url or "Log In" in resp.text or "Sign In" in resp.text:
            raise BenchmarkError(f"Authentication failed for user '{username}' at {self.base_url}")

        print(f"  Authenticated as {username}")

    def _extract_csrf_from_html(self, html):
        m = re.search(r'name=["\']csrfmiddlewaretoken["\'] value=["\']([^"\']+)["\']', html)
        return m.group(1) if m else None

    def _csrf_header(self):
        token = (
            self.session.cookies.get("cpf_csrftoken")
            or self.session.cookies.get("csrftoken")
        )
        headers = {"Referer": f"{self.base_url}/"}
        if token:
            headers["X-CSRFToken"] = token
        return headers

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def create_project(self, repo_url, run_index):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        name = f"benchmark-{ts}-{run_index}"
        payload = {
            "name": name,
            "repository_url": repo_url,
            "concurrency": 4,
        }
        resp = self.session.post(
            f"{self.base_url}/api/v1/jobs/",
            json=payload,
            headers=self._csrf_header(),
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            raise BenchmarkError(f"Failed to create project ({resp.status_code}): {resp.text[:300]}")

        body = resp.json()
        # API wraps response: {"content": [...], "data": {...}}
        data = body.get("data") or body
        self.project_id = data["id"]
        self.project_name = name
        print(f"  Created project '{name}' (ID: {self.project_id})")
        return self.project_id

    def start_indexing(self):
        payload = {"clean_index": True, "pull_before_index": False, "watch_mode": False}
        resp = self.session.post(
            f"{self.base_url}/api/v1/jobs/{self.project_id}/start/",
            json=payload,
            headers=self._csrf_header(),
            timeout=30,
        )
        if resp.status_code not in (200, 201, 202):
            raise BenchmarkError(f"Failed to start indexing ({resp.status_code}): {resp.text[:300]}")
        print(f"  Indexing started")

    def get_status(self):
        resp = self.session.get(
            f"{self.base_url}/api/v1/jobs/{self.project_id}/status/",
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        # API wraps response: {"content": [...], "data": {...}}
        return body.get("data") or body

    def stop_job(self):
        """Stop a running job before deleting."""
        try:
            self.session.post(
                f"{self.base_url}/api/v1/jobs/{self.project_id}/stop/",
                headers=self._csrf_header(),
                timeout=15,
            )
        except Exception:
            pass

    def delete_project(self):
        if not self.project_id:
            return
        resp = self.session.delete(
            f"{self.base_url}/api/v1/jobs/{self.project_id}/",
            headers=self._csrf_header(),
            timeout=30,
        )
        if resp.status_code in (200, 204):
            print(f"  Cleaned up project {self.project_id} and its ES index")
        else:
            print(f"  WARNING: cleanup returned {resp.status_code}: {resp.text[:200]}")

    def cleanup(self, current_status=None):
        if self._cleanup_done or not self.project_id:
            return
        self._cleanup_done = True
        print("\n  Cleaning up...")
        # Stop if still running
        if current_status in ("running", "pending", None):
            self.stop_job()
            time.sleep(2)
        self.delete_project()
        self.project_id = None

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    def poll_until_complete(self):
        """
        Poll status until completed/failed/stopped.
        Returns a dict of timing metrics.
        """
        TERMINAL = {"completed", "failed", "stopped"}
        stage_times = {}  # stage -> first seen timestamp
        last_stage = None
        start_time = time.time()
        last_status = None

        print(f"  Polling every {POLL_INTERVAL}s (timeout: {fmt_seconds(self.timeout)})...")
        print()

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.timeout:
                raise BenchmarkError(f"Timed out after {fmt_seconds(elapsed)}")

            status_data = self.get_status()
            if not status_data:
                time.sleep(POLL_INTERVAL)
                continue

            status = status_data.get("status")
            last_status = status
            progress = status_data.get("progress", {})
            stage = progress.get("stage") or status or "unknown"
            pct = progress.get("progress_pct", 0)
            total_files = progress.get("total_files", 0)
            files_proc = progress.get("files_processed", 0)
            es = status_data.get("elasticsearch", {})
            es_docs = es.get("document_count", 0)

            # Track stage entry times
            if stage and stage != last_stage:
                stage_times[stage] = time.time()
                last_stage = stage

            bar_width = 30
            filled = int(bar_width * pct / 100) if pct else 0
            bar = "█" * filled + "░" * (bar_width - filled)
            sys.stdout.write(
                f"\r  [{bar}] {pct:3d}%  {stage:<12}  files:{files_proc}/{total_files or '?'}  docs:{es_docs}  {fmt_seconds(elapsed)}"
            )
            sys.stdout.flush()

            if status in TERMINAL:
                print()  # newline after progress bar
                return {
                    "final_status": status,
                    "total_seconds": time.time() - start_time,
                    "total_files": total_files or files_proc,
                    "es_document_count": es_docs,
                    "stage_times": stage_times,
                    "start_time": start_time,
                }

            time.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_score(metrics):
        total_files = metrics.get("total_files", 0)
        total_seconds = metrics.get("total_seconds", 1)
        if total_files == 0 or total_seconds == 0:
            return 0.0
        return round((total_files / total_seconds) * 100, 1)

    @staticmethod
    def stage_duration(stage_times, from_stage, to_stage):
        t0 = stage_times.get(from_stage)
        t1 = stage_times.get(to_stage)
        if t0 is None or t1 is None:
            return None
        return round(t1 - t0, 1)

    # ------------------------------------------------------------------
    # Run a single benchmark
    # ------------------------------------------------------------------

    def run_once(self, repo_url, run_index, note=""):
        print(f"\n  Run #{run_index} — {self.env_name}")
        metrics = None
        try:
            self.project_id = None
            self._cleanup_done = False
            self.create_project(repo_url, run_index)
            self.start_indexing()
            metrics = self.poll_until_complete()
        except KeyboardInterrupt:
            print("\n  Interrupted by user")
            self.cleanup(current_status="running")
            raise
        except BenchmarkError:
            self.cleanup(current_status=metrics.get("final_status") if metrics else None)
            raise
        finally:
            if not self._cleanup_done:
                self.cleanup(current_status=metrics.get("final_status") if metrics else None)

        score = self.calculate_score(metrics)
        stage_times = metrics.get("stage_times", {})

        clone_secs = self.stage_duration(stage_times, "cloning", "enqueuing")
        process_secs = self.stage_duration(stage_times, "processing", "finalizing")
        if process_secs is None:
            # Fallback: total minus clone
            if clone_secs:
                process_secs = round(metrics["total_seconds"] - clone_secs, 1)

        result = {
            "env": self.env_name,
            "base_url": self.base_url,
            "repo": repo_url,
            "run": run_index,
            "status": metrics["final_status"],
            "score": score,
            "total_files": metrics["total_files"],
            "total_seconds": round(metrics["total_seconds"], 1),
            "clone_seconds": clone_secs,
            "process_seconds": process_secs,
            "es_document_count": metrics["es_document_count"],
            "note": note,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return result


# ------------------------------------------------------------------
# Output / reporting
# ------------------------------------------------------------------

def print_result(result):
    status = result["status"]
    ok = status == "completed"
    symbol = "PASS" if ok else "FAIL"
    print(f"\n  ┌── Result: {symbol} ──────────────────────────────────────")
    if ok:
        print(f"  │  Score:    {result['score']} pts  (files/sec × 100)")
    print(f"  │  Status:   {status}")
    print(f"  │  Files:    {result['total_files']}")
    print(f"  │  ES docs:  {result['es_document_count']}")
    print(f"  │  Total:    {fmt_seconds(result['total_seconds'])}")
    if result["clone_seconds"] is not None:
        print(f"  │  Clone:    {fmt_seconds(result['clone_seconds'])}")
    if result["process_seconds"] is not None:
        print(f"  │  Process:  {fmt_seconds(result['process_seconds'])}")
    if result["note"]:
        print(f"  │  Note:     {result['note']}")
    print(f"  └────────────────────────────────────────────────────")


def print_comparison(results):
    if len(results) < 2:
        return
    completed = [r for r in results if r["status"] == "completed"]
    if len(completed) < 2:
        return
    print("\n  Comparison:")
    print(f"  {'Env':<14} {'Score':>7} {'Total':>8} {'Clone':>8} {'Process':>10}")
    print(f"  {'-'*14} {'-'*7} {'-'*8} {'-'*8} {'-'*10}")
    for r in completed:
        print(
            f"  {r['env']:<14} {r['score']:>7} "
            f"{fmt_seconds(r['total_seconds']):>8} "
            f"{fmt_seconds(r['clone_seconds']):>8} "
            f"{fmt_seconds(r['process_seconds']):>10}"
        )
    scores = [r["score"] for r in completed]
    if len(scores) == 2:
        ratio = max(scores) / min(scores) if min(scores) > 0 else 0
        faster = completed[scores.index(max(scores))]["env"]
        print(f"\n  {faster} is {ratio:.1f}x faster")


# ------------------------------------------------------------------
# Memory file persistence
# ------------------------------------------------------------------

SCORES_HEADER = """---
name: Benchmark Scores
description: Indexing throughput benchmark results across environments
type: project
---

## Benchmark Results

### Score Formula
`score = (files_indexed / total_seconds) * 100` — higher is better
Consistent repo required for valid comparisons.

### Results

| Date | Env | Score | Files | Total | Clone | Process | ES Docs | Repo | Notes |
|------|-----|-------|-------|-------|-------|---------|---------|------|-------|
"""


def ensure_scores_file():
    if not SCORES_FILE.exists():
        SCORES_FILE.write_text(SCORES_HEADER)


def append_score(result):
    ensure_scores_file()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    repo_short = result["repo"].replace("https://github.com/", "")
    score_str = str(result["score"]) if result["status"] == "completed" else f"FAIL({result['status']})"
    row = (
        f"| {date} "
        f"| {result['env']} "
        f"| {score_str} "
        f"| {result['total_files']} "
        f"| {fmt_seconds(result['total_seconds'])} "
        f"| {fmt_seconds(result['clone_seconds'])} "
        f"| {fmt_seconds(result['process_seconds'])} "
        f"| {result['es_document_count']} "
        f"| {repo_short} "
        f"| {result['note'] or '-'} |\n"
    )

    content = SCORES_FILE.read_text()
    SCORES_FILE.write_text(content + row)
    print(f"\n  Score recorded in {SCORES_FILE}")


# ------------------------------------------------------------------
# Local dev performance tips
# ------------------------------------------------------------------

LOCAL_PERF_TIPS = [
    (
        "Increase ES heap size (most reliable win)",
        "CPU ELSER is the dominant bottleneck on local dev — more heap gives the "
        "ML model more room and reduces GC pauses. In docker-compose.yml set: "
        "ES_JAVA_OPTS=-Xms2g -Xmx2g  (or higher if your machine allows). "
        "Restart ES after: docker compose restart elasticsearch.",
    ),
    (
        "Pre-warm ELSER before benchmarking",
        "ELSER cold-starts on the first inference call, adding 30-60s to the first "
        "batch. Warm it up before starting: "
        "curl -s http://localhost:9200/_ml/trained_models/.elser_model_2_linux-x86_64/_stats | "
        "grep state  "
        "If state != 'fully_allocated', wait before running the benchmark.",
    ),
    (
        "Tune BATCH_SIZE in the indexer",
        "Check indexer/src/utils/elasticsearch.ts for BATCH_SIZE (currently 10). "
        "On local, smaller batches (5) reduce per-batch ELSER latency; larger batches "
        "reduce HTTP overhead. Try both and compare scores to find the local sweet spot.",
    ),
    (
        "Raise indexer concurrency",
        "Pass --concurrency 8 when starting the benchmark job (default is 4). "
        "Multiple workers pipeline file parsing and ES submission, hiding some of "
        "the ELSER latency behind parallel work.",
    ),
    (
        "Use production for authoritative regression tests",
        "CPU ELSER on local will always be slower than Elastic Cloud GPU inference. "
        "Local scores are useful for catching large regressions during development, "
        "but always confirm important perf changes with a production run before shipping.",
    ),
]


def print_local_perf_tips(score):
    print("\n  Local Dev Performance Tips")
    print("  " + "-" * 56)
    print(f"  Current score: {score} pts. Ideas to improve it:")
    for i, (title, detail) in enumerate(LOCAL_PERF_TIPS, 1):
        print(f"\n  {i}. {title}")
        # Wrap detail at 70 chars
        words = detail.split()
        line = "     "
        for word in words:
            if len(line) + len(word) + 1 > 75:
                print(line)
                line = "     " + word + " "
            else:
                line += word + " "
        if line.strip():
            print(line)
    print()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CodePathfinder Indexer Benchmark Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/benchmark.py --env local --username admin --password secret
  python scripts/benchmark.py --env production --username admin --password secret
  python scripts/benchmark.py --env local --env production  # run both, compare
  python scripts/benchmark.py --env local --runs 3 --note "batch_size=20"
  python scripts/benchmark.py --env custom --base-url http://localhost:8000 --username admin --password secret
        """,
    )

    parser.add_argument(
        "--env",
        choices=["local", "production", "custom"],
        action="append",
        dest="envs",
        required=True,
        help="Environment to test (can be specified multiple times)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL (required when --env custom)",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("CPF_BENCHMARK_USERNAME"),
        help="Django username (or set CPF_BENCHMARK_USERNAME env var)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("CPF_BENCHMARK_PASSWORD"),
        help="Django password (or set CPF_BENCHMARK_PASSWORD env var)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help=(
            "GitHub repo URL to index. Defaults per env: "
            "local=pallets/itsdangerous (~25 files), "
            "production=pallets/click (~93 files)"
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per environment (default: 1)",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Free-text note recorded with the score (e.g. 'after batch_size=20 change')",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Per-run timeout in seconds (overrides per-env default)",
    )

    args = parser.parse_args()

    # Validate
    if "custom" in args.envs and not args.base_url:
        parser.error("--base-url is required when --env custom")
    if not args.username or not args.password:
        parser.error(
            "Username and password are required. Use --username/--password or "
            "set CPF_BENCHMARK_USERNAME/CPF_BENCHMARK_PASSWORD env vars."
        )

    # Deduplicate envs while preserving order
    seen = set()
    envs = [e for e in args.envs if not (e in seen or seen.add(e))]

    print_banner()
    print(f"Runs:     {args.runs} per environment")
    print(f"Envs:     {', '.join(envs)}")
    if args.note:
        print(f"Note:     {args.note}")

    all_results = []
    interrupted = False

    for env_name in envs:
        if env_name == "custom":
            preset = {"base_url": args.base_url, "verify_ssl": True,
                      "default_repo": "https://github.com/pallets/click",
                      "default_timeout": DEFAULT_TIMEOUT}
        else:
            preset = ENV_PRESETS[env_name]

        repo = args.repo or preset["default_repo"]
        timeout = args.timeout or preset["default_timeout"]

        print(f"\n{'='*60}")
        print(f"Environment: {env_name.upper()}  ({preset['base_url']})")
        print(f"Repo:        {repo}")
        print(f"Timeout:     {fmt_seconds(timeout)}")
        print("=" * 60)

        bench = Benchmark(
            base_url=preset["base_url"],
            verify_ssl=preset["verify_ssl"],
            env_name=env_name,
            timeout=timeout,
        )

        # Register SIGINT handler for clean shutdown
        original_sigint = signal.getsignal(signal.SIGINT)

        def _sigint_handler(signum, frame):
            print("\n\n  Caught Ctrl+C — cleaning up before exit...")
            bench.cleanup(current_status="running")
            signal.signal(signal.SIGINT, original_sigint)
            sys.exit(130)

        signal.signal(signal.SIGINT, _sigint_handler)

        try:
            bench.authenticate(args.username, args.password)
        except BenchmarkError as e:
            print(f"  ERROR: {e}")
            continue

        run_results = []
        for i in range(1, args.runs + 1):
            try:
                result = bench.run_once(repo, i, note=args.note)
                run_results.append(result)
                all_results.append(result)
                print_result(result)
                append_score(result)
                if env_name == "local" and result["status"] == "completed":
                    print_local_perf_tips(result["score"])
            except KeyboardInterrupt:
                interrupted = True
                break
            except BenchmarkError as e:
                print(f"\n  ERROR: {e}")
                # Record a failed entry
                result = {
                    "env": env_name,
                    "base_url": preset["base_url"],
                    "repo": repo,
                    "run": i,
                    "status": "error",
                    "score": 0,
                    "total_files": 0,
                    "total_seconds": 0,
                    "clone_seconds": None,
                    "process_seconds": None,
                    "es_document_count": 0,
                    "note": f"ERROR: {e}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                all_results.append(result)

        signal.signal(signal.SIGINT, original_sigint)

        if interrupted:
            break

        # Summary for multiple runs
        if len(run_results) > 1:
            completed = [r for r in run_results if r["status"] == "completed"]
            if completed:
                avg_score = round(sum(r["score"] for r in completed) / len(completed), 1)
                print(f"\n  Average score ({len(completed)} runs): {avg_score}")

    # Cross-environment comparison
    if len(envs) > 1 and not interrupted:
        print(f"\n{'='*60}")
        print("COMPARISON")
        print("=" * 60)
        print_comparison(all_results)

    print(f"\n{'='*60}")
    completed_all = [r for r in all_results if r["status"] == "completed"]
    if completed_all:
        print(f"STATUS: BENCHMARK COMPLETE — {len(completed_all)}/{len(all_results)} runs succeeded")
    else:
        print(f"STATUS: ALL RUNS FAILED")
    print("=" * 60)

    sys.exit(0 if completed_all else 1)


if __name__ == "__main__":
    main()

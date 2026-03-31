#!/usr/bin/env bash
# This script is a forwarder for backwards compatibility.
# The main setup script lives at the repo root for discoverability.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/setup.sh" "$@"

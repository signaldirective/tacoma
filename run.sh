#!/usr/bin/env bash
# Launch TACOMA (Theme Aware Comprehensive Omarchy Mixer Application).
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m tacoma "$@"

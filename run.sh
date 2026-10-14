#!/usr/bin/env bash
# Launch the Omarchy PipeWire/PulseAudio mixer.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m omarchy_mixer "$@"

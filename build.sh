#!/usr/bin/env bash
#
# Build a single-file executable for the mixer.
#
# Produces dist/omarchy-mixer: one zipapp file with a shebang, runnable as-is.
# Drop it in a directory on $PATH (e.g. ~/.local/bin) and run `omarchy-mixer`.
#
#   ./build.sh              # build dist/omarchy-mixer
#   ./build.sh --install    # build, then install to ~/.local/bin/omarchy-mixer
#
set -euo pipefail
cd "$(dirname "$0")"

OUT="dist/omarchy-mixer"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -r omarchy_mixer "$STAGE/"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +

# Archive root entrypoint with a real exit code.
cat >"$STAGE/__main__.py" <<'PY'
import sys

from omarchy_mixer.app import main

if __name__ == "__main__":
    sys.exit(main())
PY

rm -rf dist
mkdir -p dist
python3 -m zipapp "$STAGE" \
  --output "$OUT" \
  --python "/usr/bin/env python3" \
  --compress
chmod 0755 "$OUT"

echo "built $OUT ($(du -h "$OUT" | cut -f1))"

if [[ "${1:-}" == "--install" ]]; then
  dest="$HOME/.local/bin"
  mkdir -p "$dest"
  install -m 0755 "$OUT" "$dest/omarchy-mixer"
  echo "installed $dest/omarchy-mixer"
  case ":$PATH:" in
    *":$dest:"*) echo "run: omarchy-mixer" ;;
    *) echo "note: $dest is not on \$PATH" ;;
  esac
fi

#!/usr/bin/env bash
#
# Build a single-file executable for TACOMA.
#
# Produces dist/tacoma: one zipapp file with a shebang, runnable as-is.
# Drop it in a directory on $PATH (e.g. ~/.local/bin) and run `tacoma`.
#
#   ./build.sh              # build dist/tacoma
#   ./build.sh --install    # build, then install to ~/.local/bin/tacoma
#
set -euo pipefail
cd "$(dirname "$0")"

OUT="dist/tacoma"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -r tacoma "$STAGE/"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +

# Archive root entrypoint with a real exit code.
cat >"$STAGE/__main__.py" <<'PY'
import sys

from tacoma.app import main

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
  install -m 0755 "$OUT" "$dest/tacoma"
  echo "installed $dest/tacoma"
  case ":$PATH:" in
    *":$dest:"*) echo "run: tacoma" ;;
    *) echo "note: $dest is not on \$PATH" ;;
  esac
fi

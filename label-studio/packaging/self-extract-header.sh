#!/usr/bin/env bash
set -euo pipefail

ARCHIVE_LINE="$(awk '/^__SUPVAN_ARCHIVE_BELOW__$/ {print NR + 1; exit}' "$0")"
if [[ -z "$ARCHIVE_LINE" ]]; then
  echo "Installer payload marker is missing." >&2
  exit 2
fi

PAYLOAD_DIR="$(mktemp -d -t supvan-label-studio-v032.XXXXXX)"
cleanup() {
  if [[ -n "${PAYLOAD_DIR:-}" && -d "$PAYLOAD_DIR" && "$PAYLOAD_DIR" == /tmp/supvan-label-studio-v032.* ]]; then
    rm -rf -- "$PAYLOAD_DIR"
  fi
}
trap cleanup EXIT

tail -n +"$ARCHIVE_LINE" "$0" | tar -xzf - -C "$PAYLOAD_DIR"
"$PAYLOAD_DIR/supvan-label-studio-v0.3.2/install.sh"
exit 0

__SUPVAN_ARCHIVE_BELOW__

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

echo "Removing SUPVAN E10 Label Studio..."
"$ROOT/label-studio/uninstall.sh" || true

echo "Removing user-scoped printer service..."
(
  cd "$ROOT/driver"
  make uninstall-user
)

rm -f "$HOME/.local/bin/supvan-e10-linux-uninstall"
SUITE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/supvan-e10-linux"
# If this script is running from the installed source snapshot, removal is safe
# after all component uninstall commands above have completed.
rm -rf "$SUITE_DIR"

echo "SUPVAN E10 Linux Suite removed from this user account."

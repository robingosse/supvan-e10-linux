#!/usr/bin/env bash
set -euo pipefail
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/supvan-label-studio"
rm -f "$HOME/.local/bin/supvan-label-studio"
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/supvan-label-studio.desktop"
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/supvan-e10-label-studio.svg"
echo "SUPVAN E10 Label Studio removed."

#!/usr/bin/env bash
set -euo pipefail
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/supvan-label-studio"
rm -f "$HOME/.local/bin/supvan-label-studio"
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/supvan-label-studio.desktop"
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/supvan-label-studio.svg"
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/mime/packages/supvan-label-studio.xml"
if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database "${XDG_DATA_HOME:-$HOME/.local/share}/mime" >/dev/null 2>&1 || true
fi
echo "SUPVAN Label Studio removed."
echo "Preferences and saved .supvanlabel files were kept."

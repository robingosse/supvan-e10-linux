#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APPDIR="${XDG_DATA_HOME:-$HOME/.local/share}/supvan-label-studio"
BINDIR="$HOME/.local/bin"
DESKTOPDIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONDIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
MIMEDIR="${XDG_DATA_HOME:-$HOME/.local/share}/mime/packages"

missing=()
for cmd in python3 lp fc-match; do command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd"); done
python3 - <<'PY' >/dev/null 2>&1 || missing+=("python modules: PIL qrcode gi")
import PIL, qrcode, gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
PY

if ((${#missing[@]})); then
  echo "Missing runtime dependencies: ${missing[*]}" >&2
  echo >&2
  echo "On Linux Mint / Ubuntu install them with:" >&2
  echo "  sudo apt install python3-gi gir1.2-gtk-3.0 python3-pil python3-qrcode cups-client fonts-dejavu-core" >&2
  exit 2
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR" "$BINDIR" "$DESKTOPDIR" "$ICONDIR" "$MIMEDIR"
cp -a "$HERE/supvan_label_studio" "$APPDIR/"
cp "$HERE/run.py" "$APPDIR/run.py"
cp "$HERE/README.md" "$APPDIR/README.md"
install -m755 "$HERE/bin/supvan-label-studio" "$BINDIR/supvan-label-studio"
install -m644 "$HERE/share/applications/supvan-label-studio.desktop" "$DESKTOPDIR/supvan-label-studio.desktop"
install -m644 "$HERE/share/icons/hicolor/scalable/apps/supvan-label-studio.svg" "$ICONDIR/supvan-label-studio.svg"
install -m644 "$HERE/share/mime/packages/supvan-label-studio.xml" "$MIMEDIR/supvan-label-studio.xml"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOPDIR" >/dev/null 2>&1 || true
fi
if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database "${XDG_DATA_HOME:-$HOME/.local/share}/mime" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "SUPVAN Label Studio installed."
echo "Version: 0.3.4"
echo "Launch from the Mint menu or run: supvan-label-studio"
echo "If ~/.local/bin is not in PATH, run: $BINDIR/supvan-label-studio"

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

need_cmds=(cargo rustc make pkg-config python3 lp lpstat bluetoothctl systemctl)
missing=()
for cmd in "${need_cmds[@]}"; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done

python_ok=1
python3 - <<'PY' >/dev/null 2>&1 || python_ok=0
import PIL, qrcode, gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
PY

if ((${#missing[@]})) || ((python_ok == 0)); then
  echo "Missing build/runtime dependencies." >&2
  ((${#missing[@]})) && echo "Commands not found: ${missing[*]}" >&2
  ((python_ok == 0)) && echo "Python modules missing: PIL/qrcode/gi(GTK3)" >&2
  cat >&2 <<'MSG'

Linux Mint / Ubuntu:
  sudo apt install build-essential cargo pkg-config libdbus-1-dev \
    bluez cups avahi-daemon python3 python3-gi gir1.2-gtk-3.0 \
    python3-pil python3-qrcode cups-client fonts-dejavu-core python3-pytest

If your distro Rust is too old for edition 2024, install a current Rust toolchain
with rustup, then run ./install.sh again.
MSG
  exit 2
fi

cat <<'MSG'
============================================================
SUPVAN E10 Linux Suite installer
  * Rust IPP/CUPS + E10/T15 printer service
  * SUPVAN E10 Label Studio
============================================================
MSG

echo "[1/5] Driver formatting/tests/check"
(
  cd "$ROOT/driver"
  cargo fmt --check
  cargo test --workspace
  cargo check --all-targets
)

echo "[2/5] Label Studio tests"
(
  cd "$ROOT/label-studio"
  PYTHONPATH=. python3 -m pytest -q
)

echo "[3/5] Install/restart user printer service"
(
  cd "$ROOT/driver"
  make deploy
)

echo "[4/5] Install Label Studio"
"$ROOT/label-studio/install.sh"

echo "[5/5] Save installed source + uninstall helper"
SUITE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/supvan-e10-linux"
SUITE_SRC="$SUITE_DIR/source"
rm -rf "$SUITE_SRC"
mkdir -p "$SUITE_SRC" "$HOME/.local/bin"
tar -C "$ROOT" \
  --exclude='.git' --exclude='dist' --exclude='driver/target' \
  --exclude='__pycache__' --exclude='.pytest_cache' \
  -cf - . | tar -C "$SUITE_SRC" -xf -
cat > "$HOME/.local/bin/supvan-e10-linux-uninstall" <<WRAP
#!/usr/bin/env bash
exec "$SUITE_SRC/uninstall.sh" "\$@"
WRAP
chmod +x "$HOME/.local/bin/supvan-e10-linux-uninstall"

echo
systemctl --user --no-pager --full status supvan-printer-app 2>/dev/null | sed -n '1,12p' || true
echo
lpstat -p 2>/dev/null || true
cat <<'MSG'

Installed.
Uninstall later with: supvan-e10-linux-uninstall

Launch "SUPVAN E10 Label Studio" from the application menu, or run:
  supvan-label-studio

If the E10 queue is not visible immediately, make sure the printer is paired,
powered on, and click Refresh beside the queue field in Label Studio.
MSG

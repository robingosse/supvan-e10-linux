#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
OUT="${1:-$ROOT/dist}"
mkdir -p "$OUT"
NAME="supvan-e10-linux-$VERSION"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/$NAME"
tar -C "$ROOT" \
  --exclude='.git' --exclude='dist' --exclude='driver/target' \
  --exclude='__pycache__' --exclude='.pytest_cache' \
  -cf - . | tar -C "$TMP/$NAME" -xf -
tar -C "$TMP" -czf "$OUT/$NAME.tar.gz" "$NAME"
sha256sum "$OUT/$NAME.tar.gz" > "$OUT/$NAME.tar.gz.sha256"
echo "$OUT/$NAME.tar.gz"

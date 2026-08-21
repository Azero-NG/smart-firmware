#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ESPHOME="$ROOT/.venv/bin/esphome"
PYTHON="$ROOT/.venv/bin/python"
YAML="$ROOT/esphome/transition.yaml"
BUILD_DIR="$ROOT/build"
PIO_DIR="$ROOT/esphome/.esphome/build/ct30w-open/.pioenvs/ct30w-open"

if [[ ! -x "$ESPHOME" || ! -x "$PYTHON" ]]; then
  echo "ERROR: create .venv and install requirements.txt first" >&2
  exit 2
fi
if [[ ! -f "$ROOT/esphome/secrets.yaml" ]]; then
  echo "ERROR: copy esphome/secrets.example.yaml to esphome/secrets.yaml and fill your own Wi-Fi values" >&2
  exit 2
fi
if grep -q 'replace-with-' "$ROOT/esphome/secrets.yaml"; then
  echo "ERROR: esphome/secrets.yaml still contains example values" >&2
  exit 2
fi

mkdir -p "$BUILD_DIR"
"$ESPHOME" config "$YAML"
"$ESPHOME" compile "$YAML"
cp "$PIO_DIR/firmware.bin" "$BUILD_DIR/CT30W_eboot_transition_native.bin"
"$PYTHON" -m esptool --chip esp8266 elf2image --version 2 \
  --flash-mode dout --flash-freq 40m --flash-size 2MB-c1 \
  -o "$BUILD_DIR/CT30W_eboot_transition_v2.bin" "$PIO_DIR/firmware.elf"
"$PYTHON" "$ROOT/tools/build_transition.py" build \
  --candidate-v2 "$BUILD_DIR/CT30W_eboot_transition_v2.bin" \
  --native "$BUILD_DIR/CT30W_eboot_transition_native.bin" \
  --output "$BUILD_DIR/ct30w-recovery.bin" \
  --metadata-output "$BUILD_DIR/transition-metadata.json"
cp "$ROOT/firmware/ORVIBO_CT30W_v2.0.15_stock_rollback.bin" "$BUILD_DIR/ct30w-stock-rollback.bin"
echo "BUILD_OK $BUILD_DIR/ct30w-recovery.bin"
echo "NEXT: cat $BUILD_DIR/transition-metadata.json"

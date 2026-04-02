#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ASSET_DIR="$ROOT_DIR/app/src/main/assets"
MODEL_DIR="$ASSET_DIR/model-en-us"
TMP_DIR="$(mktemp -d)"
ZIP_PATH="$TMP_DIR/vosk-model-small-en-us-0.15.zip"
UNPACK_DIR="$TMP_DIR/vosk-model-small-en-us-0.15"

mkdir -p "$ASSET_DIR"

curl -L -o "$ZIP_PATH" \
  https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip

unzip -q "$ZIP_PATH" -d "$TMP_DIR"
rm -rf "$MODEL_DIR"
mv "$UNPACK_DIR" "$MODEL_DIR"
printf 'en-us-small-0.15-v1\n' > "$MODEL_DIR/uuid"

echo "Installed Vosk model into $MODEL_DIR"

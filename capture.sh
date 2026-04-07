#!/bin/bash
# Sourdough Monitor — Camera capture via ffmpeg
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
OUTPUT="$SCRIPT_DIR/photos/fermento_$TIMESTAMP.jpg"

mkdir -p "$SCRIPT_DIR/photos"

/opt/homebrew/bin/ffmpeg -f avfoundation -framerate 30 -i "0" -frames:v 1 -update 1 -y "$OUTPUT" 2>/dev/null >/dev/null

if [ -f "$OUTPUT" ] && [ -s "$OUTPUT" ]; then
  ln -sf "fermento_$TIMESTAMP.jpg" "$SCRIPT_DIR/photos/latest.jpg"
  echo "$OUTPUT"
  exit 0
else
  echo "ERROR" >&2
  exit 1
fi

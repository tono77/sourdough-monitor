#!/bin/bash
# Sourdough Monitor — Captura desde cámara FaceTime HD con ffmpeg

WORKSPACE="/Users/moltbot/.openclaw/workspace/sourdough"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
OUTPUT="$WORKSPACE/photos/fermento_$TIMESTAMP.jpg"

# Crear directorio si no existe
mkdir -p "$WORKSPACE/photos"

# Captura con ffmpeg (framerate 30, 1 frame, formato uyvy422)
/opt/homebrew/bin/ffmpeg -f avfoundation -framerate 30 -i "0" -frames:v 1 -update 1 -y "$OUTPUT" 2>/dev/null >/dev/null

if [ -f "$OUTPUT" ] && [ -s "$OUTPUT" ]; then
  echo "$OUTPUT"
  exit 0
else
  echo "ERROR" >&2
  exit 1
fi

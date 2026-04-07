#!/bin/bash
# Daemon de captura continua — se ejecuta cada 30 segundos
# Mantiene la última foto fresca para que el cron la use

WORKSPACE="/Users/moltbot/.openclaw/workspace/sourdough"
LOG="$WORKSPACE/data/sourdough.log"

while true; do
  TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
  OUTPUT="$WORKSPACE/photos/fermento_$TIMESTAMP.jpg"
  
  mkdir -p "$WORKSPACE/photos"
  
  # Capturar con ffmpeg
  /opt/homebrew/bin/ffmpeg -f avfoundation -framerate 30 -i "0" -frames:v 1 -update 1 -y "$OUTPUT" 2>/dev/null >/dev/null
  
  if [ -f "$OUTPUT" ] && [ -s "$OUTPUT" ]; then
    echo "[$(date)] ✅ Captura exitosa: $OUTPUT" >> "$LOG"
    # Mantener un symlink a la última foto para acceso rápido
    ln -sf "$OUTPUT" "$WORKSPACE/photos/latest.jpg"
  else
    echo "[$(date)] ⚠️ Captura fallida" >> "$LOG"
  fi
  
  # Esperar 5 minutos antes de siguiente captura
  sleep 300
done

#!/usr/bin/env python3
"""
Sourdough Monitor — Análisis de imagen con Claude Vision
Mide el nivel del fermento en el frasco y lo guarda en SQLite.
"""

import sys
import os
import sqlite3
import base64
import json
import re
import requests
import subprocess
import mimetypes
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("/Users/moltbot/.openclaw/workspace/sourdough")
DB_PATH = WORKSPACE / "data" / "fermento.db"
PHOTOS_DIR = WORKSPACE / "photos"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mediciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            foto_path TEXT NOT NULL,
            nivel_pct REAL,         -- % de crecimiento vs baseline
            nivel_px INTEGER,        -- altura estimada en píxeles
            burbujas TEXT,           -- ninguna/pocas/muchas
            textura TEXT,            -- lisa/rugosa/activa
            notas TEXT,              -- observación del modelo
            es_peak INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn

def compress_image(photo_path, target_size_mb=3):
    """Comprime imagen JPG a menos de 5MB para Claude."""
    # Usar ffmpeg para recompresar
    compressed_path = str(photo_path).replace(".jpg", "_compressed.jpg")
    
    # Estima calidad inicial
    quality = 85
    for attempt in range(5):
        subprocess.run([
            "ffmpeg", "-i", str(photo_path),
            "-q:v", str(quality),
            "-y", compressed_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        
        size_mb = os.path.getsize(compressed_path) / (1024 * 1024)
        if size_mb < target_size_mb:
            return compressed_path
        quality -= 5
    
    return compressed_path

def encode_image(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")

def analyze_photo(photo_path: str, baseline_nivel: float = None) -> dict:
    """Envía foto a Claude Haiku y extrae métricas del fermento."""
    
    # Leer API key de Anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        config_paths = [
            "/Users/moltbot/.openclaw/config.json",
            os.path.expanduser("~/.openclaw/config.json"),
        ]
        for cp in config_paths:
            if os.path.exists(cp):
                with open(cp) as f:
                    cfg = json.load(f)
                api_key = cfg.get("anthropic", {}).get("apiKey", "")
                if api_key:
                    break

    if not api_key:
        raise ValueError("No se encontró ANTHROPIC_API_KEY")

    # Comprimir imagen si es necesario
    photo_to_encode = photo_path
    if os.path.getsize(photo_path) > 4 * 1024 * 1024:
        photo_to_encode = compress_image(photo_path)
    
    img_b64 = encode_image(photo_to_encode)
    
    # Detectar tipo MIME basado en la extensión real del archivo
    ext = Path(photo_path).suffix.lower()
    if ext == ".png":
        media_type = "image/png"
    elif ext in [".jpg", ".jpeg"]:
        media_type = "image/jpeg"
    elif ext == ".webp":
        media_type = "image/webp"
    elif ext == ".gif":
        media_type = "image/gif"
    else:
        # Fallback: intentar detectar por la extensión del archivo a codificar
        detected_type, _ = mimetypes.guess_type(photo_to_encode)
        media_type = detected_type or "image/jpeg"
    
    baseline_txt = ""
    if baseline_nivel is not None:
        baseline_txt = f"El nivel baseline (inicio) fue de {baseline_nivel}% del frasco."

    prompt = f"""Eres un analizador experto de masa madre (sourdough starter).
Analiza esta foto del frasco de fermento y responde SOLO con JSON válido, sin texto adicional.

{baseline_txt}

Busca en la imagen:
1. Una marca de referencia (cinta, marcador) en el frasco que indica el nivel inicial
2. El nivel actual del fermento (la superficie visible)
3. La actividad del fermento (burbujas, textura)

Responde con este JSON exacto:
{{
  "nivel_pct": <número 0-200, donde 100=nivel inicial, 150=creció 50%, etc.>,
  "nivel_px": <altura estimada de la superficie del fermento en píxeles desde la base>,
  "burbujas": "<ninguna|pocas|muchas>",
  "textura": "<lisa|rugosa|muy_activa>",
  "notas": "<observación breve en español, máx 100 chars>",
  "visible_marca": <true|false, si se ve la marca de referencia>
}}

Si no puedes ver el frasco claramente, usa nivel_pct: null."""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-haiku-4-5",
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_b64
                        }
                    },
                    {"type": "text", "text": prompt}
                ]
            }]
        },
        timeout=30
    )
    
    result = response.json()
    if "error" in result:
        raise ValueError(f"Claude API error: {result['error']['message']}")
    
    text = result["content"][0]["text"].strip()
    
    # Extraer JSON del texto
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(text)

def save_measurement(conn, photo_path, analysis):
    timestamp = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO mediciones (timestamp, foto_path, nivel_pct, nivel_px, burbujas, textura, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp,
        photo_path,
        analysis.get("nivel_pct"),
        analysis.get("nivel_px"),
        analysis.get("burbujas"),
        analysis.get("textura"),
        analysis.get("notas")
    ))
    conn.commit()
    print(f"[{timestamp}] Nivel: {analysis.get('nivel_pct')}% | Burbujas: {analysis.get('burbujas')} | {analysis.get('notas')}")

def detect_peak(conn):
    """Detecta el primer descenso (inicio del peak)."""
    # Obtener últimas 2 mediciones
    rows = conn.execute("""
        SELECT id, nivel_pct FROM mediciones 
        WHERE nivel_pct IS NOT NULL 
        ORDER BY id DESC LIMIT 2
    """).fetchall()
    
    if len(rows) < 2:
        return False, None
    
    # rows está ordenado descendente, invertir para obtener orden cronológico
    prev_level = rows[1][1]  # medición anterior
    curr_level = rows[0][1]  # medición actual
    
    # Detectar si ya hay un peak registrado
    peak_count = conn.execute("SELECT COUNT(*) FROM mediciones WHERE es_peak=1").fetchone()[0]
    
    # Peak si es el primer descenso Y aún no hay peak registrado
    if curr_level < prev_level and peak_count == 0:
        # El peak ocurrió en la medición anterior (el máximo antes del descenso)
        peak_row = conn.execute("""
            SELECT timestamp, nivel_pct FROM mediciones 
            WHERE nivel_pct = (SELECT MAX(nivel_pct) FROM mediciones)
            LIMIT 1
        """).fetchone()
        return True, peak_row
    
    return False, None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 analyze.py <ruta_foto.jpg>")
        sys.exit(1)
    
    photo_path = sys.argv[1]
    conn = init_db()
    
    # Obtener baseline (primer nivel registrado)
    baseline = conn.execute("SELECT nivel_pct FROM mediciones ORDER BY id LIMIT 1").fetchone()
    baseline_nivel = baseline[0] if baseline else None
    
    print(f"Analizando: {photo_path}")
    analysis = analyze_photo(photo_path, baseline_nivel)
    save_measurement(conn, photo_path, analysis)
    
    # Verificar peak
    is_peak, peak_info = detect_peak(conn)
    if is_peak:
        print(f"\n🎯 PEAK DETECTADO! Máximo en: {peak_info[0]} con nivel {peak_info[1]}%")
        conn.execute("UPDATE mediciones SET es_peak=1 WHERE timestamp=?", (peak_info[0],))
        conn.commit()
    
    conn.close()

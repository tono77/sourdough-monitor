#!/usr/bin/env python3
"""
Sourdough Monitor — Claude Vision analysis
Analyzes sourdough starter photos using Claude Haiku for fermentation metrics.
"""

import sys
import os
import base64
import json
import re
import requests
import subprocess
import mimetypes
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    """Load configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def get_api_key():
    """Get Anthropic API key from environment, .env file, or config files."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        return api_key

    # Check .env file in project root
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if api_key:
                        return api_key

    # Check openclaw config
    config_paths = [
        Path.home() / ".openclaw" / "config.json",
        Path("/Users/moltbot/.openclaw/config.json"),
    ]
    for cp in config_paths:
        if cp.exists():
            with open(cp) as f:
                cfg = json.load(f)
            api_key = cfg.get("anthropic", {}).get("apiKey", "")
            if api_key:
                return api_key

    raise ValueError("No ANTHROPIC_API_KEY found. Set it in .env, as environment variable, or in ~/.openclaw/config.json")


def compress_image(photo_path, target_size_mb=3):
    """Compress image to fit Claude's size limits."""
    compressed_path = str(photo_path).replace(".jpg", "_compressed.jpg")
    quality = 85
    for attempt in range(5):
        subprocess.run([
            "ffmpeg", "-i", str(photo_path),
            "-q:v", str(quality),
            "-y", compressed_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)

        if os.path.exists(compressed_path):
            size_mb = os.path.getsize(compressed_path) / (1024 * 1024)
            if size_mb < target_size_mb:
                return compressed_path
        quality -= 5

    return compressed_path


def encode_image(path):
    """Encode image to base64."""
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def detect_media_type(photo_path):
    """Detect MIME type from file extension."""
    ext = Path(photo_path).suffix.lower()
    type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return type_map.get(ext, "image/jpeg")


def analyze_photo(photo_path, baseline_foto_path=None, baseline_nivel=None, tiempo_min=None):
    """Send photo to Claude and extract fermentation metrics.

    If baseline_foto_path is provided (comparative mode), Claude receives BOTH the baseline
    photo and the current photo and estimates RELATIVE growth — much more accurate than
    single-photo absolute estimation.
    """
    api_key = get_api_key()
    config = load_config()
    model = config.get("claude", {}).get("model", "claude-haiku-4-5")

    # Prepare current photo
    photo_to_encode = str(photo_path)
    if os.path.getsize(photo_path) > 4 * 1024 * 1024:
        photo_to_encode = compress_image(photo_path)
    current_b64 = encode_image(photo_to_encode)
    current_media = detect_media_type(photo_path)

    # Decide whether to use comparative mode
    use_comparative = (
        baseline_foto_path is not None and
        Path(baseline_foto_path).exists() and
        str(baseline_foto_path) != str(photo_path)
    )

    if use_comparative:
        # Prepare baseline photo
        baseline_to_encode = str(baseline_foto_path)
        if os.path.getsize(baseline_foto_path) > 4 * 1024 * 1024:
            baseline_to_encode = compress_image(baseline_foto_path)
        baseline_b64 = encode_image(baseline_to_encode)
        baseline_media = detect_media_type(baseline_foto_path)
        tiempo_txt = f" ({tiempo_min:.0f} minutos después)" if tiempo_min else ""

        prompt = f"""Eres un experto en análisis visual de fermentación de masa madre.

Se te muestran DOS fotos del MISMO frasco de fermento:
- IMAGEN 1 (primera): Foto INICIAL del día. El fermento está en su nivel de partida.
- IMAGEN 2 (segunda): Foto ACTUAL{tiempo_txt}.

Tu tarea:
1. Identifica la MARCA DE REFERENCIA en el frasco (cinta adhesiva, marcador, banda de goma)
2. Compara la altura de la superficie visible del fermento entre ambas fotos
3. Estima cuánto ha crecido el fermento: 100=igual al inicio, 150=creció 50% más
4. Asigna tu nivel de confianza en la medición

Responde SOLO con JSON válido, sin texto adicional:
{{
  "nivel_pct": <número: 100=igual a inicio, 120=creció 20%, etc. Usa null si no puedes comparar>,
  "burbujas": "<ninguna|pocas|muchas>",
  "textura": "<lisa|rugosa|muy_activa>",
  "notas": "<observación breve en español, máx 100 chars>",
  "visible_marca": <true|false, si se ve la marca de referencia en la imagen actual>,
  "confianza": <1-5; 5=marca visible y comparación clara, 3=estimación razonable, 1=no pude ver bien>
}}

Regla: nivel_pct >= 100 salvo que el fermento claramente haya bajado del nivel inicial."""

        content = [
            {"type": "image", "source": {"type": "base64", "media_type": baseline_media, "data": baseline_b64}},
            {"type": "image", "source": {"type": "base64", "media_type": current_media,  "data": current_b64}},
            {"type": "text", "text": prompt}
        ]

    else:
        # Single-photo fallback (first measurement of a session, or no baseline photo)
        baseline_txt = f"\nEl nivel inicial fue {baseline_nivel:.0f}% del frasco." if baseline_nivel else ""

        prompt = f"""Eres un analizador experto de masa madre (sourdough starter).
Analiza esta foto del frasco de fermento y responde SOLO con JSON válido.
{baseline_txt}
Busca:
1. La MARCA DE REFERENCIA en el frasco (cinta adhesiva, marcador, banda de goma) = nivel 100%
2. La superficie actual visible del fermento

Responde con JSON:
{{
  "nivel_pct": <número 0-200, donde 100=nivel de la marca, 150=creció 50% sobre la marca>,
  "burbujas": "<ninguna|pocas|muchas>",
  "textura": "<lisa|rugosa|muy_activa>",
  "notas": "<observación breve en español, máx 100 chars>",
  "visible_marca": <true|false>,
  "confianza": <1-5; 5=marca visible y medición clara, 1=imagen poco clara>
}}
Si no puedes ver el frasco, usa nivel_pct: null y confianza: 1."""

        content = [
            {"type": "image", "source": {"type": "base64", "media_type": current_media, "data": current_b64}},
            {"type": "text", "text": prompt}
        ]

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": model,
            "max_tokens": 400,
            "messages": [{"role": "user", "content": content}]
        },
        timeout=45
    )

    result = response.json()
    if "error" in result:
        raise ValueError(f"Claude API error: {result['error']['message']}")

    text = result["content"][0]["text"].strip()

    # Extract JSON from response
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(text)


def capture_photo():
    """Capture a photo from the camera using ffmpeg."""
    config = load_config()
    camera_index = config.get("capture", {}).get("camera_index", "0")

    photos_dir = BASE_DIR / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output = photos_dir / f"fermento_{timestamp}.jpg"

    try:
        result = subprocess.run(
            [
                "/opt/homebrew/bin/ffmpeg",
                "-f", "avfoundation",
                "-framerate", "30",
                "-i", camera_index,
                "-frames:v", "1",
                "-update", "1",
                "-y", str(output)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15
        )

        if output.exists() and output.stat().st_size > 1000:
            # Create latest.jpg symlink
            latest = photos_dir / "latest.jpg"
            if latest.exists() or latest.is_symlink():
                latest.unlink()
            latest.symlink_to(output.name)
            print(f"📸 Captured: {output.name} ({output.stat().st_size / 1024:.0f}KB)")
            return str(output)
        else:
            print(f"⚠️ Capture failed: file too small or missing")
            return None
    except subprocess.TimeoutExpired:
        print("⚠️ Camera capture timed out")
        return None
    except Exception as e:
        print(f"⚠️ Capture error: {e}")
        return None


if __name__ == "__main__":
    from db import init_db, save_measurement as db_save, detect_peak

    if len(sys.argv) < 2:
        # Auto-capture mode
        photo = capture_photo()
        if not photo:
            print("Failed to capture photo")
            sys.exit(1)
    else:
        photo = sys.argv[1]

    conn = init_db()

    # Get baseline
    baseline = conn.execute(
        "SELECT nivel_pct FROM mediciones WHERE nivel_pct IS NOT NULL ORDER BY id LIMIT 1"
    ).fetchone()
    baseline_nivel = baseline[0] if baseline else None

    print(f"🔍 Analyzing: {photo}")
    analysis = analyze_photo(photo, baseline_nivel)
    print(f"   Level: {analysis.get('nivel_pct')}% | Bubbles: {analysis.get('burbujas')} | {analysis.get('notas')}")

    conn.close()

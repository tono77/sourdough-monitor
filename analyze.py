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
from cv_analyze import analyze_photo_cv

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
    """Send photo to Claude API and extract fermentation metrics."""
    api_key = get_api_key()
    config = load_config()
    model = config.get("claude", {}).get("model", "claude-3-haiku-20240307")

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

        # In-Context Learning (Few Shot): Read corrections if any
        corrections_context = ""
        try:
            corr_file = Path("data/dataset_corrections.json")
            if corr_file.exists():
                with open(corr_file, "r") as f:
                    corrections = json.load(f)
                if corrections:
                    # Get up to 3 most recent corrections
                    recent = corrections[-3:]
                    corrections_context = "HISTORIAL DE CORRECCIONES MANUALES RECIENTES DEL USUARIO:\n"
                    for c in recent:
                        corrections_context += f"- A las {c.get('timestamp','').split('T')[-1][:5]}, el usuario reportó que el nivel real de crecimiento era: {c.get('nivel_pct')}%.\n"
                    corrections_context += "\nUtiliza esta escala como referencia absoluta para la foto de ahora.\n\n"
        except Exception:
            pass

        prompt = f"""Eres un experto en análisis visual de fermentación de masa madre.

Se te muestran DOS fotos del MISMO frasco{tiempo_txt}:
- IMAGEN 1: Foto INICIAL del día.
- IMAGEN 2: Foto ACTUAL.

{corrections_context}
MÉTODO DE MEDICIÓN (sigue exactamente):
1. ESPACIO DE COORDENADAS: En esta imagen, asume como ser humano que 0% es la BASE INFERIOR del frasco (vacío total) y 100% es la TAPA SUPERIOR del frasco (lleno total).
2. Encuentra la línea horizontal exacta de la superficie superior de la MASA MADRE. 
3. Llama A = El volumen tridimensional inicial marcado por la banda roja en la foto 1. Observa qué "rayita" o marca del vidrio abarca.
4. Llama B = El volumen tridimensional actual de la masa en la foto 2. Guiate estrictamente por las "rayitas" horizontales impresas en el frasco.
5. nivel_pct = Calcula mentalmente el % de crecimiento volumétrico. ¡Si el volumen se duplicó, es 100%! Por ejemplo, si en la foto 1 la masa ocupaba 2 rayitas del frasco, y en la foto 2 subió hasta ocupar 4 rayitas, ¡eso es exactamente un 100% de crecimiento! Si ocupa 5 rayitas, es un 150%. 
6. ¡IMPORTANTÍSIMO! No uses regla de tres con los píxeles de la foto (la perspectiva deforma la imagen y hace que las rayitas de arriba parezcan más pequeñas). Usa las rayas impresas físicas en el vidrio como tu única regla absoluta. Mide la SUPERFICIE DE LA MASA. Responde en "nivel_pct" directamente tu % estimado final.

Responde SOLO con JSON válido:
{{
  "nivel_pct": <tu % de crecimiento calculado guiándote por las marcas del frasco>,
  "altura_inicial_pct": <A: tu estimación mental del nivel original>,
  "altura_actual_pct": <B: % de frasco lleno en foto 2>,
  "burbujas": "<ninguna|pocas|muchas>",
  "textura": "<lisa|rugosa|muy_activa>",
  "notas": "<observación en español, concéntrate en si la MASA superó la banda elástica, máx 100 chars>",
  "visible_marca": <true|false>,
  "confianza": <1-5>
}}"""

    # In-Context Learning (Few Shot): Read corrections if any
    corrections_context = ""
    try:
        corr_file = Path("data/dataset_corrections.json")
        if corr_file.exists():
            with open(corr_file, "r") as f:
                corrections = json.load(f)
            if corrections:
                # Get up to 3 most recent corrections
                recent = corrections[-3:]
                corrections_context = "HISTORIAL DE CORRECCIONES MANUALES RECIENTES DEL USUARIO:\n"
                for c in recent:
                    corrections_context += f"- A las {c.get('timestamp','').split('T')[-1][:5]}, el usuario reportó que el nivel real de crecimiento era: {c.get('nivel_pct')}%.\n"
                corrections_context += "\nUtiliza esta escala como referencia absoluta para la foto de ahora.\n\n"
    except Exception as e:
        pass

    if use_comparative:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": baseline_media, "data": baseline_b64}},
            {"type": "image", "source": {"type": "base64", "media_type": current_media, "data": current_b64}},
            {"type": "text", "text": prompt}
        ]
    else:
        prompt = f"""Eres un analizador experto de masa madre (sourdough starter).
Analiza esta foto del frasco de fermento.
{corrections_context}
MÉTODO DE MEDICIÓN:
1. ESPACIO DE COORDENADAS: En la imagen visualizada, asume tu intuición habitual: 0% es la BASE plana del frasco de cristal (vacío) y 100% es el BORDE SUPERIOR de la tapa (lleno).
2. Vas a ver tu referencia: Una banda elástica (generalmente roja) abrazando el frasco.
3. Encuentra la línea horizontal donde reposa la superficie superior de la MASA real dentro del vidrio.
4. Estima la posición Y (altura) de la BANDA ELASTICA en este espacio 0-100%.
5. Estima la posición Y (altura) de la SUPERFICIE DE LA MASA en este espacio 0-100%.

Responde SOLO con JSON válido:
{{
  "altura_y_pct": <% del frasco donde está la superficie actual del fermento (EJEMPLO: 42.5)>,
  "altura_banda_pct": <% del frasco donde está la banda/cinta>,
  "burbujas": "<ninguna|pocas|muchas>",
  "textura": "<lisa|rugosa|muy_activa>",
  "notas": "<observación en español, máx 100 chars>",
  "visible_marca": <true|false>
}}
Si no puedes ver el frasco, usa altura_y_pct: null."""
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": current_media, "data": current_b64}},
            {"type": "text", "text": prompt}
        ]

    config = load_config()
    model = config.get("claude", {}).get("model", "claude-3-haiku-20240307")

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": model,
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": content
            }]
        },
        timeout=30
    )

    try:
        raw_resp = response.json()
        if "content" not in raw_resp:
            print(f"⚠️ Claude unexpected response: {raw_resp}")
        
        text = raw_resp["content"][0]["text"]
        # Claude might wrap JSON in markdown blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        analysis_data = json.loads(text)
    except Exception as e:
        print(f"⚠️ Failed to parse Claude response: {e}")
        # Graceful fallback: If AI vision goes down, OpenCV geometry ensures the math succeeds!
        analysis_data = {
            "burbujas": "Pocas",
            "textura": "Estándar",
            "notas": "Modo Clínico: Medición Matemática por OpenCV (IA inactiva por error de red)"
        }
        
    # Inject deterministic Computer Vision processing!
    try:
        from db import init_db
        conn = init_db()
        ses = conn.execute("SELECT izq_x_pct, der_x_pct, base_y_pct, tope_y_pct, fondo_y_pct FROM sesiones WHERE estado='activa' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        
        if ses and ses[0] is not None and ses[1] is not None and ses[2] is not None and ses[3] is not None:
            calib_data = {"izq_x_pct": ses[0], "der_x_pct": ses[1], "base_y_pct": ses[2], "tope_y_pct": ses[3], "fondo_y_pct": ses[4]}
            cv_altura = analyze_photo_cv(photo_path, calib_data)
            if cv_altura is not None:
                # We feed OpenCV straight into the pipeline!
                analysis_data["altura_y_pct"] = cv_altura
                analysis_data["modo_analisis"] = "OpenCV + Sonnet"
                analysis_data["visible_marca"] = True
    except Exception as e:
        print(f"⚠️ OpenCV Processing Error: {e}")
        
    return analysis_data


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
                "-ss", "00:00:02",
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

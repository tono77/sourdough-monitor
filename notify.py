#!/usr/bin/env python3
"""
Sourdough Monitor — Email notification module
Sends periodic email updates with fermentation status and dashboard link.
"""

import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_email_config():
    """Load email configuration from config.json."""
    if not CONFIG_PATH.exists():
        return None
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    email_cfg = cfg.get("email", {})
    if not email_cfg.get("enabled"):
        return None
    if not email_cfg.get("sender") or not email_cfg.get("password") or not email_cfg.get("recipient"):
        return None
    return email_cfg


FIREBASE_DASHBOARD_URL = "https://sourdough-monitor-app.web.app"


def get_dashboard_url():
    """Return Firebase Hosting dashboard URL."""
    return FIREBASE_DASHBOARD_URL


def send_update_email(session, latest_measurement, measurement_count, elapsed_hours, photo_url=None):
    """Send a fermentation update email."""
    config = load_email_config()
    if not config:
        return False

    dashboard_url = get_dashboard_url()
    now = datetime.now()

    # Build status info
    nivel = latest_measurement.get("nivel_pct", "N/A") if latest_measurement else "N/A"
    burbujas = latest_measurement.get("burbujas", "N/A") if latest_measurement else "N/A"
    textura = latest_measurement.get("textura", "N/A") if latest_measurement else "N/A"
    notas = latest_measurement.get("notas", "") if latest_measurement else ""

    # Emoji for bubble level
    burbuja_emoji = {"ninguna": "⚪", "pocas": "🟡", "muchas": "🟢"}.get(burbujas, "⚪")
    # Emoji for texture
    textura_emoji = {"lisa": "😴", "rugosa": "😊", "muy_activa": "🔥"}.get(textura, "😴")

    subject = f"🍞 Masa Madre — {now.strftime('%H:%M')} | Nivel: {nivel}%"

    html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; margin: 0;">
        <div style="max-width: 500px; margin: 0 auto; background: #16213e; border-radius: 16px; padding: 24px; border: 1px solid rgba(255,255,255,0.1);">
            <h1 style="color: #ff6b35; font-size: 20px; margin: 0 0 16px 0;">🍞 Sourdough Monitor</h1>
            <p style="color: #999; font-size: 13px; margin: 0 0 20px 0;">
                Sesión: {session.get('fecha', 'N/A')} &bull; {elapsed_hours:.1f}h transcurridas &bull; {measurement_count} mediciones
            </p>

            <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                <tr>
                    <td style="padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px 0 0 0; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
                        <div style="font-size: 24px; font-weight: bold; color: #e94560;">{nivel}%</div>
                        <div style="font-size: 11px; color: #888;">Nivel</div>
                    </td>
                    <td style="padding: 12px; background: rgba(255,255,255,0.05); text-align: center; border: 1px solid rgba(255,255,255,0.05);">
                        <div style="font-size: 24px;">{burbuja_emoji}</div>
                        <div style="font-size: 11px; color: #888;">{burbujas}</div>
                    </td>
                    <td style="padding: 12px; background: rgba(255,255,255,0.05); text-align: center; border: 1px solid rgba(255,255,255,0.05);">
                        <div style="font-size: 24px;">{textura_emoji}</div>
                        <div style="font-size: 11px; color: #888;">{textura}</div>
                    </td>
                    <td style="padding: 12px; background: rgba(255,255,255,0.05); border-radius: 0 8px 0 0; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
                        <div style="font-size: 24px; font-weight: bold; color: #ffc107;">{elapsed_hours:.1f}h</div>
                        <div style="font-size: 11px; color: #888;">Tiempo</div>
                    </td>
                </tr>
            </table>

            <p style="color: #ccc; font-size: 13px; margin: 0 0 20px 0; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 8px; border-left: 3px solid #ff6b35;">
                💬 {notas}
            </p>

            {f'''
            <div style="margin-bottom: 20px; border-radius: 12px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1);">
                <img src="{photo_url}" alt="Última captura" style="width: 100%; display: block; max-height: 300px; object-fit: cover;">
            </div>
            ''' if photo_url else ''}

            <a href="{dashboard_url}" style="display: block; text-align: center; background: linear-gradient(135deg, #ff6b35, #e94560); color: white; text-decoration: none; padding: 14px 24px; border-radius: 12px; font-weight: 600; font-size: 15px;">
                📊 Ver Dashboard en Vivo
            </a>

            <p style="color: #555; font-size: 11px; text-align: center; margin: 16px 0 0 0;">
                Próximo update en 1 hora · Activo de 07:00 a 23:00
            </p>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["sender"]
    msg["To"] = config["recipient"]
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["sender"], config["password"])
            server.sendmail(config["sender"], config["recipient"], msg.as_string())
        print(f"📧 Email sent to {config['recipient']}")
        return True
    except Exception as e:
        print(f"⚠️ Email failed: {e}")
        return False


def send_peak_alert(session, peak_info):
    """Send a special alert when fermentation peak is detected."""
    config = load_email_config()
    if not config:
        return False

    dashboard_url = get_dashboard_url()
    nivel = peak_info.get("nivel", "N/A")
    timestamp = peak_info.get("timestamp", "N/A")

    subject = f"🎯 ¡PEAK DETECTADO! Masa Madre alcanzó {nivel}%"

    html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; margin: 0;">
        <div style="max-width: 500px; margin: 0 auto; background: #16213e; border-radius: 16px; padding: 24px; border: 2px solid #ffd700;">
            <h1 style="color: #ffd700; font-size: 24px; margin: 0 0 8px 0; text-align: center;">🎯 ¡PEAK DETECTADO!</h1>
            <p style="color: #ffc107; font-size: 16px; text-align: center; margin: 0 0 20px 0;">
                Tu masa madre alcanzó su punto máximo
            </p>

            <div style="text-align: center; padding: 24px; background: rgba(255,215,0,0.1); border-radius: 12px; margin-bottom: 20px;">
                <div style="font-size: 48px; font-weight: bold; color: #ffd700;">{nivel}%</div>
                <div style="font-size: 13px; color: #999; margin-top: 4px;">Nivel máximo alcanzado</div>
                <div style="font-size: 12px; color: #888; margin-top: 8px;">📅 {timestamp}</div>
            </div>

            <p style="color: #ccc; font-size: 14px; text-align: center; margin: 0 0 20px 0;">
                ⏰ Es momento de usar tu masa madre para hornear.
                <br>El fermento comenzará a descender desde ahora.
            </p>

            <a href="{dashboard_url}" style="display: block; text-align: center; background: linear-gradient(135deg, #ffd700, #ff6b35); color: #1a1a2e; text-decoration: none; padding: 14px 24px; border-radius: 12px; font-weight: 700; font-size: 15px;">
                📊 Ver Dashboard
            </a>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["sender"]
    msg["To"] = config["recipient"]
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["sender"], config["password"])
            server.sendmail(config["sender"], config["recipient"], msg.as_string())
        print(f"🎯📧 Peak alert sent to {config['recipient']}")
        return True
    except Exception as e:
        print(f"⚠️ Peak email failed: {e}")
        return False

"""Email notifications — deduplicated templates, single send helper."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sourdough.config import AppConfig, EmailConfig
from sourdough.models import Measurement, Session

log = logging.getLogger(__name__)


def _send_html(email_cfg: EmailConfig, subject: str, html_body: str) -> bool:
    """Send an HTML email via SMTP. Returns True on success."""
    if not email_cfg.enabled or not email_cfg.sender or not email_cfg.password:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_cfg.sender
    msg["To"] = email_cfg.recipient
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port) as server:
            server.starttls()
            server.login(email_cfg.sender, email_cfg.password)
            server.sendmail(email_cfg.sender, email_cfg.recipient, msg.as_string())
        log.info("Email sent to %s", email_cfg.recipient)
        return True
    except Exception as e:
        log.warning("Email failed: %s", e)
        return False


def send_update_email(
    config: AppConfig,
    session: Session,
    latest: Measurement | None,
    measurement_count: int,
    elapsed_hours: float,
    photo_url: str | None = None,
) -> bool:
    """Send a fermentation update email."""
    from datetime import datetime

    nivel = latest.nivel_pct if latest and latest.nivel_pct is not None else "N/A"
    burbujas = latest.burbujas if latest else "N/A"
    textura = latest.textura if latest else "N/A"
    notas = latest.notas if latest else ""

    burbuja_emoji = {"ninguna": "⚪", "pocas": "🟡", "muchas": "🟢"}.get(burbujas, "⚪")
    textura_emoji = {"lisa": "😴", "rugosa": "😊", "muy_activa": "🔥"}.get(textura, "😴")

    if isinstance(nivel, (int, float)):
        nivel_str = f"+{nivel}%" if nivel > 0 else f"{nivel}%"
    else:
        nivel_str = str(nivel)

    velocity_html = ""
    now = datetime.now()

    subject = f"🍞 Masa Madre — {now.strftime('%H:%M')} | Crecimiento: {nivel_str}"

    photo_block = ""
    if photo_url:
        photo_block = f"""
            <div style="margin-bottom: 20px; border-radius: 12px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1);">
                <img src="{photo_url}" alt="Última captura" style="width: 100%; display: block; max-height: 300px; object-fit: cover;">
            </div>"""

    html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; margin: 0;">
        <div style="max-width: 500px; margin: 0 auto; background: #16213e; border-radius: 16px; padding: 24px; border: 1px solid rgba(255,255,255,0.1);">
            <h1 style="color: #ff6b35; font-size: 20px; margin: 0 0 16px 0;">🍞 Sourdough Monitor</h1>
            <p style="color: #999; font-size: 13px; margin: 0 0 20px 0;">
                Sesión: {session.fecha} &bull; {elapsed_hours:.1f}h transcurridas &bull; {measurement_count} mediciones
            </p>

            <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                <tr>
                    <td style="padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px 0 0 0; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
                        <div style="font-size: 24px; font-weight: bold; color: #e94560; margin-bottom: 2px;">{nivel_str}</div>
                        <div style="font-size: 11px; color: #888; font-weight: bold;">TOTAL</div>
                        {velocity_html}
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
                {notas}
            </p>

            {photo_block}

            <a href="{config.dashboard_url}" style="display: block; text-align: center; background: linear-gradient(135deg, #ff6b35, #e94560); color: white; text-decoration: none; padding: 14px 24px; border-radius: 12px; font-weight: 600; font-size: 15px;">
                Ver Dashboard en Vivo
            </a>

            <p style="color: #555; font-size: 11px; text-align: center; margin: 16px 0 0 0;">
                Próximo update en 1 hora · Activo de {config.schedule.start_hour:02d}:{config.schedule.start_minute:02d} a {config.schedule.end_hour:02d}:{config.schedule.end_minute:02d}
            </p>
        </div>
    </body>
    </html>"""

    return _send_html(config.email, subject, html_body)


def send_peak_alert(config: AppConfig, session: Session, peak_info: dict) -> bool:
    """Send a special alert when fermentation peak is detected."""
    nivel = peak_info.get("nivel", "N/A")
    timestamp = peak_info.get("timestamp", "N/A")
    nivel_str = f"+{nivel}%" if isinstance(nivel, (int, float)) and nivel > 0 else f"{nivel}%"

    subject = f"🎯 ¡PEAK DETECTADO! Masa Madre creció {nivel_str}"

    html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; margin: 0;">
        <div style="max-width: 500px; margin: 0 auto; background: #16213e; border-radius: 16px; padding: 24px; border: 2px solid #ffd700;">
            <h1 style="color: #ffd700; font-size: 24px; margin: 0 0 8px 0; text-align: center;">¡PEAK DETECTADO!</h1>
            <p style="color: #ffc107; font-size: 16px; text-align: center; margin: 0 0 20px 0;">
                Tu masa madre alcanzó su punto máximo
            </p>
            <div style="text-align: center; padding: 24px; background: rgba(255,215,0,0.1); border-radius: 12px; margin-bottom: 20px;">
                <div style="font-size: 48px; font-weight: bold; color: #ffd700;">{nivel_str}</div>
                <div style="font-size: 13px; color: #999; margin-top: 4px;">Crecimiento máximo alcanzado</div>
                <div style="font-size: 12px; color: #888; margin-top: 8px;">{timestamp}</div>
            </div>
            <p style="color: #ccc; font-size: 14px; text-align: center; margin: 0 0 20px 0;">
                Es momento de usar tu masa madre para hornear.
                <br>El fermento comenzará a descender desde ahora.
            </p>
            <a href="{config.dashboard_url}" style="display: block; text-align: center; background: linear-gradient(135deg, #ffd700, #ff6b35); color: #1a1a2e; text-decoration: none; padding: 14px 24px; border-radius: 12px; font-weight: 700; font-size: 15px;">
                Ver Dashboard
            </a>
        </div>
    </body>
    </html>"""

    return _send_html(config.email, subject, html_body)

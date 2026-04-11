"""Camera capture service — ffmpeg photo capture."""

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from sourdough.config import AppConfig

log = logging.getLogger(__name__)


def capture_photo(config: AppConfig) -> str | None:
    """Capture a photo from the camera using ffmpeg.

    Returns the absolute path to the captured image, or None on failure.
    """
    photos_dir = config.photos_dir
    photos_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output = photos_dir / f"fermento_{timestamp}.jpg"

    try:
        subprocess.run(
            [
                "/opt/homebrew/bin/ffmpeg",
                "-f", "avfoundation",
                "-framerate", "30",
                "-i", config.capture.camera_index,
                "-ss", "00:00:02",
                "-frames:v", "1",
                "-update", "1",
                "-y", str(output),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )

        if output.exists() and output.stat().st_size > 1000:
            # Update latest.jpg symlink
            latest = photos_dir / "latest.jpg"
            if latest.exists() or latest.is_symlink():
                latest.unlink()
            latest.symlink_to(output.name)
            log.info("Captured: %s (%dKB)", output.name, output.stat().st_size // 1024)
            return str(output)
        else:
            log.warning("Capture failed: file too small or missing")
            return None

    except subprocess.TimeoutExpired:
        log.warning("Camera capture timed out")
        return None
    except Exception as e:
        log.warning("Capture error: %s", e)
        return None


def flash_screen() -> None:
    """Produce a soft flash by waking the display and opening a white page."""
    try:
        subprocess.run(["caffeinate", "-u", "-t", "2"], check=False)
        flash_file = Path("data/flash.html").resolve()
        flash_file.parent.mkdir(parents=True, exist_ok=True)
        flash_file.write_text(
            "<html><body style='background-color:white; margin:0;'></body></html>"
        )
        subprocess.run(["open", "-a", "Safari", str(flash_file)], check=False)
        import time
        time.sleep(1.5)
    except Exception as e:
        log.warning("Soft flash warning: %s", e)


def restore_screen() -> None:
    """Close the blank white page."""
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to close front window'],
            check=False,
        )
    except Exception:
        pass

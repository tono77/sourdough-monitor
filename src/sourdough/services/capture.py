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


_BRIGHTNESS_WARNED = False


def flash_screen() -> None:
    """Wake the display so the white wallpaper illuminates the jar.

    macOS 15+ restricts the private brightness framework used by the
    `brightness` Homebrew CLI (returns kIOReturnNotPermitted). We rely on:
      1. `caffeinate -u` to wake the display (triggers user-activity signal).
      2. The user's white wallpaper/lockscreen to reflect light onto the jar.
      3. The user having auto-brightness disabled in System Settings.

    If `brightness` is still available, we opportunistically try it, but
    don't depend on success.
    """
    global _BRIGHTNESS_WARNED
    try:
        # Wake the display and keep the assertion held long enough for ffmpeg
        # to run (the ffmpeg capture uses -ss 00:00:02, so several seconds).
        subprocess.Popen(
            ["caffeinate", "-u", "-t", "8"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Try to bump brightness — silently fails on macOS 15+.
        result = subprocess.run(
            ["brightness", "1.0"],
            capture_output=True, text=True, check=False, timeout=2,
        )
        if result.returncode != 0 or "failed" in (result.stderr or "").lower():
            if not _BRIGHTNESS_WARNED:
                log.warning(
                    "brightness CLI not functional (macOS 15+ restricts the API). "
                    "Photos rely on ambient brightness. Disable auto-brightness "
                    "in System Settings → Displays and set brightness to max "
                    "before overnight monitoring."
                )
                _BRIGHTNESS_WARNED = True
        import time
        time.sleep(2.0)  # Give the display a moment to fully wake/draw.
    except Exception as e:
        log.warning("Soft flash warning: %s", e)


def restore_screen() -> None:
    """No-op now — brightness CLI doesn't work, and we don't want to dim
    mid-cycle anyway (the display will sleep on its own schedule)."""
    return

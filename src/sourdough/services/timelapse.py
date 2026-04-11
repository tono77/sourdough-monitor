"""Timelapse MP4 generation from session photos."""

import logging
import os
import subprocess
from pathlib import Path

from sourdough.models import Measurement

log = logging.getLogger(__name__)


def generate_timelapse(
    session_id: int,
    measurements: list[Measurement],
    data_dir: Path,
) -> str | None:
    """Generate an MP4 timelapse from session photos.

    Returns the path to the generated video, or None on failure.
    """
    try:
        photo_paths = [
            m.foto_path for m in measurements
            if m.foto_path and os.path.exists(m.foto_path)
        ]

        if len(photo_paths) < 2:
            return None

        concat_file = data_dir / f"concat_{session_id}.txt"
        concat_file.parent.mkdir(parents=True, exist_ok=True)

        with open(concat_file, "w") as f:
            for p in photo_paths:
                f.write(f"file '{p}'\nduration 0.25\n")

        output_file = data_dir / f"timelapse_{session_id}.mp4"

        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "warning",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(output_file),
            ],
            check=True,
        )

        # Cleanup concat file
        try:
            concat_file.unlink()
        except OSError:
            pass

        if output_file.exists():
            log.info("Timelapse generated: %s", output_file.name)
            return str(output_file)

    except Exception as e:
        log.warning("Error creating timelapse: %s", e)

    return None

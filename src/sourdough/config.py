"""Unified configuration: defaults → config.json → .env

Secrets (API keys, SMTP password) come from .env only.
User-facing settings come from config.json.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ScheduleConfig:
    start_hour: int = 7
    start_minute: int = 0
    end_hour: int = 23
    end_minute: int = 0


@dataclass(frozen=True)
class CaptureConfig:
    interval_seconds: int = 300
    camera_index: str = "0"


@dataclass(frozen=True)
class AppConfig:
    # Paths
    base_dir: Path = field(default_factory=lambda: Path.cwd())
    data_dir: Path = field(default_factory=lambda: Path.cwd() / "data")
    photos_dir: Path = field(default_factory=lambda: Path.cwd() / "photos")
    charts_dir: Path = field(default_factory=lambda: Path.cwd() / "charts")
    log_path: Path = field(default_factory=lambda: Path.cwd() / "data" / "sourdough.log")
    db_path: Path = field(default_factory=lambda: Path.cwd() / "data" / "fermento.db")

    # Secrets (from .env)
    anthropic_api_key: str = ""

    # Sub-configs
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)

    # Claude
    claude_model: str = "claude-3-haiku-20240307"

    # Firebase
    firebase_enabled: bool = True
    firebase_service_account: Optional[Path] = None
    gdrive_credentials: Optional[Path] = None
    gdrive_token: Optional[Path] = None

    # ML model
    ml_model_path: Optional[Path] = None

    # Dashboard URL (Firebase Hosting)
    dashboard_url: str = "https://sourdough-monitor-app.web.app"


def _load_dotenv(env_path: Path) -> dict[str, str]:
    """Minimal .env parser — no external dependency needed at import time."""
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip().strip("'\"")
    return values


def load_config(base_dir: Optional[Path] = None) -> AppConfig:
    """Load configuration from defaults → config.json → .env."""
    if base_dir is None:
        # Walk up from this file to find config.json
        base_dir = Path(__file__).resolve().parent.parent.parent
        if not (base_dir / "config.json").exists():
            base_dir = Path.cwd()

    config_path = base_dir / "config.json"
    env_path = base_dir / ".env"
    data_dir = base_dir / "data"

    # Load JSON config
    cfg: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)

    # Load .env secrets
    env = _load_dotenv(env_path)
    api_key = os.environ.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_API_KEY", "")

    # Schedule
    sched_raw = cfg.get("schedule", {})
    schedule_config = ScheduleConfig(
        start_hour=sched_raw.get("start_hour", 7),
        start_minute=sched_raw.get("start_minute", 0),
        end_hour=sched_raw.get("end_hour", 23),
        end_minute=sched_raw.get("end_minute", 0),
    )

    # Capture
    cap_raw = cfg.get("capture", {})
    capture_config = CaptureConfig(
        interval_seconds=cap_raw.get("interval_seconds", 300),
        camera_index=str(cap_raw.get("camera_index", "0")),
    )

    # Claude model
    claude_model = cfg.get("claude", {}).get("model", "claude-3-haiku-20240307")

    # Firebase paths
    sa_path = data_dir / "firebase-service-account.json"
    gdrive_creds = data_dir / "gdrive_credentials.json"
    gdrive_token = data_dir / "gdrive_token.json"

    # ML model
    ml_model = data_dir / "ml_model.pth"

    return AppConfig(
        base_dir=base_dir,
        data_dir=data_dir,
        photos_dir=base_dir / "photos",
        charts_dir=base_dir / "charts",
        log_path=data_dir / "sourdough.log",
        db_path=data_dir / "fermento.db",
        anthropic_api_key=api_key,
        schedule=schedule_config,
        capture=capture_config,
        claude_model=claude_model,
        firebase_enabled=True,
        firebase_service_account=sa_path if sa_path.exists() else None,
        gdrive_credentials=gdrive_creds if gdrive_creds.exists() else None,
        gdrive_token=gdrive_token,
        ml_model_path=ml_model if ml_model.exists() else None,
        dashboard_url="https://sourdough-monitor-app.web.app",
    )

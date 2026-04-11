"""Tests for config loading."""

import json
import tempfile
from pathlib import Path

from sourdough.config import load_config


class TestConfig:

    def test_defaults_when_no_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(Path(tmpdir))
            assert config.capture.interval_seconds == 300
            assert config.schedule.start_hour == 7
            assert config.claude_model == "claude-3-haiku-20240307"
            assert config.email.enabled is False

    def test_loads_from_config_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            cfg = {
                "capture": {"interval_seconds": 600, "camera_index": "1"},
                "claude": {"model": "claude-sonnet-4-6"},
                "schedule": {"start_hour": 8, "email_interval_seconds": 1800},
            }
            (base / "config.json").write_text(json.dumps(cfg))

            config = load_config(base)
            assert config.capture.interval_seconds == 600
            assert config.capture.camera_index == "1"
            assert config.claude_model == "claude-sonnet-4-6"
            assert config.schedule.start_hour == 8

    def test_loads_api_key_from_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / ".env").write_text("ANTHROPIC_API_KEY=sk-test-123\n")

            config = load_config(base)
            assert config.anthropic_api_key == "sk-test-123"

    def test_env_overrides_json_email_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            cfg = {
                "email": {
                    "enabled": True,
                    "sender": "test@test.com",
                    "password": "json-password",
                    "recipient": "dest@test.com",
                },
            }
            (base / "config.json").write_text(json.dumps(cfg))
            (base / ".env").write_text("SMTP_PASSWORD=env-password\n")

            config = load_config(base)
            assert config.email.password == "env-password"

    def test_paths_relative_to_base_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            config = load_config(base)
            assert config.db_path == base / "data" / "fermento.db"
            assert config.photos_dir == base / "photos"
            assert config.charts_dir == base / "charts"

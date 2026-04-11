#!/usr/bin/env python3
"""Entry point for `python -m sourdough`."""

import sys
import os

# macOS gRPC fork bug mitigation (Required because OpenCV forks AVFoundation)
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "False"
os.environ["GRPC_POLL_STRATEGY"] = "poll"

from sourdough.config import load_config
from sourdough.log import setup_logging


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="sourdough",
        description="Sourdough fermentation monitor with AI vision analysis",
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="Start in dashboard-only mode (no capture/analysis)",
    )
    args = parser.parse_args()

    config = load_config()
    setup_logging(config.log_path)

    from sourdough.services.monitor import Monitor

    monitor = Monitor(config)
    monitor.run(dashboard_only=args.dashboard)


if __name__ == "__main__":
    main()

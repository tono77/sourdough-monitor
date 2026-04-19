#!/usr/bin/env python3
"""One-shot retrain: sync corrections from Firestore, rebuild dataset, train.

Thin orchestrator that runs the three steps that otherwise would be invoked
separately. Use this at end-of-day (or whenever you've accumulated enough
corrections in the dashboard) to produce a fresh `data/ml_model.pth`.

The monitor picks up the new weights only on next startup, so kill it
after this finishes if you want the new model live immediately.

Usage:
    .venv/bin/python3 scripts/ml/retrain_from_corrections.py
    .venv/bin/python3 scripts/ml/retrain_from_corrections.py --epochs 30 --lr 1e-4
    .venv/bin/python3 scripts/ml/retrain_from_corrections.py --skip-sync   # use existing manual_labels.json as-is
"""

import argparse
import subprocess
import sys
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for _ in range(10):
        if (p / "data" / "fermento.db").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    sys.exit("Could not locate data/fermento.db walking up from the script.")


def run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(cwd))
    if r.returncode != 0:
        sys.exit(f"Step failed (exit {r.returncode}): {' '.join(cmd)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-sync", action="store_true",
                    help="Don't pull Firestore corrections — retrain on whatever manual_labels.json currently has.")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--python", default=None,
                    help="Python interpreter for each step (defaults to the one running this script).")
    args = ap.parse_args()

    root = find_repo_root(Path(__file__).parent)
    py = args.python or sys.executable

    if not args.skip_sync:
        run([py, str(root / "scripts/ml/sync_corrections.py")], root)

    run([py, str(root / "scripts/ml/prepare_dataset.py")], root)

    run([py, str(root / "scripts/ml/train.py"),
         "--epochs", str(args.epochs),
         "--batch-size", str(args.batch_size),
         "--lr", str(args.lr),
         "--patience", str(args.patience)], root)

    print("\n" + "=" * 60)
    print("Retrain complete. To load the new weights:")
    print("  kill $(pgrep -f 'python -m sourdough')")
    print("launchd KeepAlive auto-restarts the monitor with the new model.")


if __name__ == "__main__":
    main()

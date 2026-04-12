#!/usr/bin/env python3
"""Evaluate the trained model and generate visualizations.

Usage:
    python scripts/ml/evaluate.py
"""

import csv
import math
from pathlib import Path

import torch
import torch.nn as nn
from torchvision import transforms
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = BASE_DIR / "data" / "ml_dataset"
MODEL_PATH = BASE_DIR / "data" / "ml_model.pth"

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


def load_model(device):
    from torchvision import models
    model = models.resnet18(weights=None)
    model.fc = nn.Sequential(
        nn.Linear(512, 64),
        nn.ReLU(),
        nn.Dropout(0.2),
        nn.Linear(64, 1),
        nn.Sigmoid(),
    )
    model.load_state_dict(torch.load(MODEL_PATH, map_location=device, weights_only=True))
    model.to(device)
    model.eval()
    return model


def main():
    if not MODEL_PATH.exists():
        print(f"Model not found: {MODEL_PATH}")
        print("Run train.py first.")
        return

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = load_model(device)

    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])

    # Load all samples
    labels_path = DATASET_DIR / "labels.csv"
    crops_dir = DATASET_DIR / "crops"
    samples = []
    with open(labels_path) as f:
        for row in csv.DictReader(f):
            row["altura_pct"] = float(row["altura_pct"])
            samples.append(row)

    # Predict on all samples
    results = []
    for s in samples:
        img = Image.open(crops_dir / s["filename"]).convert("RGB")
        tensor = transform(img).unsqueeze(0).to(device)
        with torch.no_grad():
            pred = model(tensor).item() * 100.0  # back to 0-100 scale

        results.append({
            "filename": s["filename"],
            "actual": s["altura_pct"],
            "predicted": round(pred, 2),
            "error": round(abs(pred - s["altura_pct"]), 2),
            "session_id": s["session_id"],
        })

    # Metrics
    errors = [r["error"] for r in results]
    actuals = [r["actual"] for r in results]
    preds = [r["predicted"] for r in results]

    mae = sum(errors) / len(errors)
    rmse = math.sqrt(sum(e ** 2 for e in errors) / len(errors))

    mean_actual = sum(actuals) / len(actuals)
    ss_res = sum((a - p) ** 2 for a, p in zip(actuals, preds))
    ss_tot = sum((a - mean_actual) ** 2 for a in actuals)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    print(f"{'='*50}")
    print(f"MODEL EVALUATION — {len(results)} samples")
    print(f"{'='*50}")
    print(f"  MAE:  {mae:.2f}%")
    print(f"  RMSE: {rmse:.2f}%")
    print(f"  R²:   {r2:.4f}")
    print(f"  Max error: {max(errors):.2f}%")
    print()

    # Worst predictions
    results.sort(key=lambda r: r["error"], reverse=True)
    print("Worst 10 predictions:")
    print(f"  {'Filename':<45} {'Actual':>7} {'Predicted':>9} {'Error':>7}")
    print(f"  {'-'*70}")
    for r in results[:10]:
        print(f"  {r['filename']:<45} {r['actual']:>6.1f}% {r['predicted']:>8.1f}% {r['error']:>6.1f}%")

    # Per-session breakdown
    print(f"\nPer-session MAE:")
    session_ids = sorted(set(r["session_id"] for r in results))
    for sid in session_ids:
        session_results = [r for r in results if r["session_id"] == sid]
        session_mae = sum(r["error"] for r in session_results) / len(session_results)
        print(f"  Session {sid}: MAE={session_mae:.2f}% ({len(session_results)} samples)")

    # Save detailed results
    results_path = DATASET_DIR / "evaluation_results.csv"
    with open(results_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "actual", "predicted", "error", "session_id"])
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda r: r["filename"]))
    print(f"\nDetailed results saved to: {results_path}")


if __name__ == "__main__":
    main()

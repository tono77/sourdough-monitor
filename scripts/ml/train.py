#!/usr/bin/env python3
"""Train a ResNet18 model to predict sourdough surface height.

Fine-tunes a pretrained ResNet18 on calibrated jar crops.
Outputs model weights to data/ml_model.pth.

Usage:
    python scripts/ml/train.py [--epochs 30] [--lr 1e-4] [--batch-size 16]
"""

import argparse
import csv
import hashlib
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = BASE_DIR / "data" / "ml_dataset"
MODEL_PATH = BASE_DIR / "data" / "ml_model.pth"

# ImageNet normalization
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class SourdoughDataset(Dataset):
    """Dataset of jar crops with altura_pct labels."""

    def __init__(self, samples: list[dict], crops_dir: Path, transform=None):
        self.samples = samples
        self.crops_dir = crops_dir
        self.transform = transform

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        s = self.samples[idx]
        img = Image.open(self.crops_dir / s["filename"]).convert("RGB")
        if self.transform:
            img = self.transform(img)
        label = torch.tensor(s["altura_pct"] / 100.0, dtype=torch.float32)  # normalize to 0-1
        return img, label


def build_model():
    """ResNet18 with single regression output."""
    model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
    # Freeze early layers (learn high-level features only)
    for param in list(model.parameters())[:-20]:
        param.requires_grad = False
    model.fc = nn.Sequential(
        nn.Linear(512, 64),
        nn.ReLU(),
        nn.Dropout(0.2),
        nn.Linear(64, 1),
        nn.Sigmoid(),  # output in [0, 1]
    )
    return model


def load_samples():
    """Load labels.csv and return list of sample dicts."""
    labels_path = DATASET_DIR / "labels.csv"
    if not labels_path.exists():
        raise FileNotFoundError(f"Run prepare_dataset.py first: {labels_path}")

    samples = []
    with open(labels_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["altura_pct"] = float(row["altura_pct"])
            row["session_id"] = int(row["session_id"])
            samples.append(row)
    return samples


def split_data(samples, val_ratio=0.15, test_ratio=0.10):
    """Deterministic split: each sample's fold is fixed by hash(filename).

    Reshuffling between runs would move samples across val/test, so the
    reported MAE would shift even when the model is identical. Hashing
    the filename pins every existing sample to the same fold forever;
    only newly-added samples land in a new bucket (with probability
    test_ratio + val_ratio of being evaluation data).
    """
    train, val, test = [], [], []
    cutoff_test = test_ratio
    cutoff_val = test_ratio + val_ratio
    for s in samples:
        h = hashlib.md5(s["filename"].encode()).hexdigest()
        bucket = int(h[:8], 16) / 0xFFFFFFFF
        if bucket < cutoff_test:
            test.append(s)
        elif bucket < cutoff_val:
            val.append(s)
        else:
            train.append(s)
    return train, val, test


def train_epoch(model, loader, optimizer, criterion, device):
    model.train()
    total_loss = 0
    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        optimizer.zero_grad()
        preds = model(imgs).squeeze()
        if preds.dim() == 0:
            preds = preds.unsqueeze(0)
        if labels.dim() == 0:
            labels = labels.unsqueeze(0)
        loss = criterion(preds, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * len(labels)
    return total_loss / len(loader.dataset)


def evaluate(model, loader, criterion, device):
    model.eval()
    total_loss = 0
    all_preds, all_labels = [], []
    with torch.no_grad():
        for imgs, labels in loader:
            imgs, labels = imgs.to(device), labels.to(device)
            preds = model(imgs).squeeze()
            if preds.dim() == 0:
                preds = preds.unsqueeze(0)
            if labels.dim() == 0:
                labels = labels.unsqueeze(0)
            total_loss += criterion(preds, labels).item() * len(labels)
            # Convert back to 0-100 scale for MAE
            all_preds.extend((preds * 100).cpu().tolist())
            all_labels.extend((labels * 100).cpu().tolist())
    avg_loss = total_loss / len(loader.dataset)
    mae = sum(abs(p - l) for p, l in zip(all_preds, all_labels)) / len(all_preds)
    return avg_loss, mae


def main():
    parser = argparse.ArgumentParser(description="Train sourdough height predictor")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--patience", type=int, default=7)
    args = parser.parse_args()

    # Device
    if torch.backends.mps.is_available():
        device = torch.device("mps")
        print("Using Apple Silicon GPU (MPS)")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
        print("Using CUDA GPU")
    else:
        device = torch.device("cpu")
        print("Using CPU")

    # Load and split data
    samples = load_samples()
    print(f"Total samples: {len(samples)}")

    train_samples, val_samples, test_samples = split_data(samples)
    print(f"Split: train={len(train_samples)}, val={len(val_samples)}, test={len(test_samples)}")

    # Transforms
    train_transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.05),
        transforms.RandomRotation(3),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])

    val_transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])

    crops_dir = DATASET_DIR / "crops"
    train_ds = SourdoughDataset(train_samples, crops_dir, train_transform)
    val_ds = SourdoughDataset(val_samples, crops_dir, val_transform)
    test_ds = SourdoughDataset(test_samples, crops_dir, val_transform)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    # Model
    model = build_model().to(device)
    optimizer = torch.optim.Adam(filter(lambda p: p.requires_grad, model.parameters()),
                                 lr=args.lr, weight_decay=1e-5)
    criterion = nn.MSELoss()

    # Training loop
    best_val_loss = float("inf")
    best_val_mae = float("inf")
    best_epoch = 0
    patience_counter = 0

    print(f"\nTraining for up to {args.epochs} epochs (patience={args.patience})...")
    print(f"{'Epoch':>5} | {'Train Loss':>10} | {'Val Loss':>10} | {'Val MAE':>8} | {'Status'}")
    print("-" * 60)

    for epoch in range(1, args.epochs + 1):
        train_loss = train_epoch(model, train_loader, optimizer, criterion, device)
        val_loss, val_mae = evaluate(model, val_loader, criterion, device)

        status = ""
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_val_mae = val_mae
            best_epoch = epoch
            patience_counter = 0
            torch.save(model.state_dict(), MODEL_PATH)
            status = "* saved"
        else:
            patience_counter += 1
            if patience_counter >= args.patience:
                status = "early stop"

        print(f"{epoch:5d} | {train_loss:10.6f} | {val_loss:10.6f} | {val_mae:7.2f}% | {status}")

        if patience_counter >= args.patience:
            break

    # Final evaluation on test set
    print(f"\n{'='*60}")
    print("Test set evaluation (best model):")
    model.load_state_dict(torch.load(MODEL_PATH, weights_only=True))
    test_loss, test_mae = evaluate(model, test_loader, criterion, device)
    print(f"  Best Epoch: {best_epoch}")
    print(f"  Best Val MAE: {best_val_mae:.2f}%")
    print(f"  Test Loss: {test_loss:.6f}")
    print(f"  Test MAE:  {test_mae:.2f}%")
    print(f"\nModel saved to: {MODEL_PATH}")
    print(f"Model size: {MODEL_PATH.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()

"""Local ML model for sourdough surface height prediction.

Loads a fine-tuned ResNet18 and predicts altura_pct from a photo.
Falls back gracefully if PyTorch is not installed or model not found.
"""

import logging
from pathlib import Path
from typing import Optional

from sourdough.models import CalibrationBounds

log = logging.getLogger(__name__)

# ImageNet normalization constants
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

# Default crop for uncalibrated sessions
DEFAULT_CROP = {"izq_x_pct": 25.0, "der_x_pct": 75.0, "tope_y_pct": 20.0, "base_y_pct": 85.0}


class MLPredictor:
    """Wraps the trained ResNet18 for inference."""

    def __init__(self, model_path: Path, device: str = "auto"):
        self._model = None
        self._transform = None
        self._device = None
        self._model_path = model_path

        try:
            import torch
            import torch.nn as nn
            from torchvision import models, transforms

            # Select device
            if device == "auto":
                if torch.backends.mps.is_available():
                    self._device = torch.device("mps")
                elif torch.cuda.is_available():
                    self._device = torch.device("cuda")
                else:
                    self._device = torch.device("cpu")
            else:
                self._device = torch.device(device)

            # Build model architecture (must match train.py)
            model = models.resnet18(weights=None)
            model.fc = nn.Sequential(
                nn.Linear(512, 64),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(64, 1),
                nn.Sigmoid(),
            )

            # Load weights
            model.load_state_dict(
                torch.load(str(model_path), map_location=self._device, weights_only=True)
            )
            model.to(self._device)
            model.eval()
            self._model = model

            # Inference transform (no augmentation)
            self._transform = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ])

            log.info("ML model loaded from %s (device: %s)", model_path.name, self._device)

        except ImportError:
            log.warning("PyTorch not installed — ML predictor disabled")
        except FileNotFoundError:
            log.warning("ML model not found: %s", model_path)
        except Exception as e:
            log.warning("Failed to load ML model: %s", e)

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def predict(self, photo_path: str, calibration: Optional[CalibrationBounds] = None) -> Optional[float]:
        """Predict surface height from a photo.

        Args:
            photo_path: Path to the jar photo.
            calibration: Calibration bounds for cropping. Uses defaults if None.

        Returns:
            altura_pct (0-100) or None if prediction fails.
        """
        if not self.is_ready:
            return None

        try:
            import torch
            from PIL import Image

            img = Image.open(photo_path).convert("RGB")

            # Crop to jar region
            crop = self._get_crop_bounds(calibration)
            w, h = img.size
            left = int(w * crop["izq_x_pct"] / 100)
            right = int(w * crop["der_x_pct"] / 100)
            top = int(h * crop["tope_y_pct"] / 100)
            bottom = int(h * crop["base_y_pct"] / 100)
            img = img.crop((left, top, right, bottom))

            # Transform and predict
            tensor = self._transform(img).unsqueeze(0).to(self._device)
            with torch.no_grad():
                pred = self._model(tensor).item() * 100.0  # scale to 0-100

            return round(pred, 1)

        except Exception as e:
            log.warning("ML prediction error: %s", e)
            return None

    def _get_crop_bounds(self, calibration: Optional[CalibrationBounds]) -> dict:
        if calibration and calibration.is_complete:
            return {
                "izq_x_pct": calibration.izq_x_pct,
                "der_x_pct": calibration.der_x_pct,
                "tope_y_pct": calibration.tope_y_pct,
                "base_y_pct": calibration.base_y_pct,
            }
        return DEFAULT_CROP

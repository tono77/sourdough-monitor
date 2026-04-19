"""Domain models — plain dataclasses, no DB or API dependency."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CalibrationBounds:
    """Jar calibration boundaries as percentages of image dimensions."""
    fondo_y_pct: Optional[float] = None   # Red band Y position
    tope_y_pct: Optional[float] = None    # Jar lid Y position
    base_y_pct: Optional[float] = None    # Jar bottom Y position
    izq_x_pct: Optional[float] = None     # Left boundary X
    der_x_pct: Optional[float] = None     # Right boundary X

    @property
    def is_complete(self) -> bool:
        return all(v is not None for v in [
            self.izq_x_pct, self.der_x_pct, self.base_y_pct, self.tope_y_pct,
        ])


@dataclass
class Session:
    """A fermentation session (usually one per day)."""
    id: int
    fecha: str
    hora_inicio: str
    hora_fin: Optional[str] = None
    estado: str = "activa"
    num_mediciones: int = 0
    peak_nivel: Optional[float] = None
    peak_timestamp: Optional[str] = None
    notas: Optional[str] = None
    calibration: CalibrationBounds = field(default_factory=CalibrationBounds)
    is_calibrated: bool = False
    timelapse_url: Optional[str] = None
    timelapse_file_id: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "Session":
        """Build from a sqlite3.Row dict."""
        return cls(
            id=row["id"],
            fecha=row["fecha"],
            hora_inicio=row["hora_inicio"],
            hora_fin=row.get("hora_fin"),
            estado=row.get("estado", "activa"),
            num_mediciones=row.get("num_mediciones", 0),
            peak_nivel=row.get("peak_nivel"),
            peak_timestamp=row.get("peak_timestamp"),
            notas=row.get("notas"),
            calibration=CalibrationBounds(
                fondo_y_pct=row.get("fondo_y_pct"),
                tope_y_pct=row.get("tope_y_pct"),
                base_y_pct=row.get("base_y_pct"),
                izq_x_pct=row.get("izq_x_pct"),
                der_x_pct=row.get("der_x_pct"),
            ),
            is_calibrated=bool(row.get("is_calibrated", 0)),
            timelapse_url=row.get("timelapse_url"),
            timelapse_file_id=row.get("timelapse_file_id"),
        )


@dataclass
class Measurement:
    """A single fermentation measurement at a point in time."""
    id: Optional[int] = None
    sesion_id: Optional[int] = None
    timestamp: str = ""
    foto_path: str = ""
    nivel_pct: Optional[float] = None
    nivel_px: Optional[int] = None
    burbujas: str = ""
    textura: str = ""
    notas: str = ""
    es_peak: bool = False
    confianza: Optional[int] = None
    modo_analisis: Optional[str] = None
    altura_y_pct: Optional[float] = None
    # v2 measurement fields
    altura_pct: Optional[float] = None        # fused surface position (0-100% of jar)
    crecimiento_pct: Optional[float] = None   # volumetric growth from baseline
    fuente: Optional[str] = None              # "claude" | "opencv" | "fusionado"
    # ML prediction (kept separate from fusion — shown side-by-side for comparison)
    ml_altura_pct: Optional[float] = None     # ResNet prediction, 0-100% of jar
    # v3 ml-based fields (derived from jar's printed scale — more accurate than %)
    volumen_ml: Optional[float] = None        # dough surface in ml (0-700)
    crecimiento_ml: Optional[float] = None    # ml change vs cycle baseline
    crecimiento_ml_pct: Optional[float] = None  # same % as crecimiento_pct but ml-sourced

    @classmethod
    def from_row(cls, row: dict) -> "Measurement":
        """Build from a sqlite3.Row dict."""
        return cls(
            id=row.get("id"),
            sesion_id=row.get("sesion_id"),
            timestamp=row.get("timestamp", ""),
            foto_path=row.get("foto_path", ""),
            nivel_pct=row.get("nivel_pct"),
            nivel_px=row.get("nivel_px"),
            burbujas=row.get("burbujas", ""),
            textura=row.get("textura", ""),
            notas=row.get("notas", ""),
            es_peak=bool(row.get("es_peak", 0)),
            confianza=row.get("confianza"),
            modo_analisis=row.get("modo_analisis"),
            altura_y_pct=row.get("altura_y_pct"),
            altura_pct=row.get("altura_pct"),
            crecimiento_pct=row.get("crecimiento_pct"),
            fuente=row.get("fuente"),
            ml_altura_pct=row.get("ml_altura_pct"),
            volumen_ml=row.get("volumen_ml"),
            crecimiento_ml=row.get("crecimiento_ml"),
            crecimiento_ml_pct=row.get("crecimiento_ml_pct"),
        )

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        return {
            "timestamp": self.timestamp,
            "foto_path": self.foto_path,
            "nivel_pct": self.nivel_pct,
            "nivel_px": self.nivel_px,
            "burbujas": self.burbujas,
            "textura": self.textura,
            "notas": self.notas,
            "es_peak": int(self.es_peak),
            "confianza": self.confianza,
            "modo_analisis": self.modo_analisis,
            "altura_y_pct": self.altura_y_pct,
            "altura_pct": self.altura_pct,
            "crecimiento_pct": self.crecimiento_pct,
            "fuente": self.fuente,
            "ml_altura_pct": self.ml_altura_pct,
            "volumen_ml": self.volumen_ml,
            "crecimiento_ml": self.crecimiento_ml,
            "crecimiento_ml_pct": self.crecimiento_ml_pct,
        }

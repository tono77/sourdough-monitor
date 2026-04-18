-- Absolute volume measurement via jar's printed ml scale
-- volumen_ml:     dough surface in ml (50-650, derived from scale + band anchor)
-- crecimiento_ml: ml change vs cycle baseline (signed)
-- crecimiento_ml_pct: same as crecimiento_pct but computed from ml (more accurate)

ALTER TABLE mediciones ADD COLUMN volumen_ml REAL DEFAULT NULL;
ALTER TABLE mediciones ADD COLUMN crecimiento_ml REAL DEFAULT NULL;
ALTER TABLE mediciones ADD COLUMN crecimiento_ml_pct REAL DEFAULT NULL;

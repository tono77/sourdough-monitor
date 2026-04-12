-- Add standardized measurement fields: fused position + calculated growth

ALTER TABLE mediciones ADD COLUMN altura_pct REAL DEFAULT NULL;
ALTER TABLE mediciones ADD COLUMN crecimiento_pct REAL DEFAULT NULL;
ALTER TABLE mediciones ADD COLUMN fuente TEXT DEFAULT NULL;

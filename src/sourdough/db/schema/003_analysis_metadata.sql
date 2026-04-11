-- Add analysis metadata columns to mediciones

ALTER TABLE mediciones ADD COLUMN confianza INTEGER DEFAULT NULL;
ALTER TABLE mediciones ADD COLUMN modo_analisis TEXT DEFAULT NULL;
ALTER TABLE mediciones ADD COLUMN altura_y_pct REAL DEFAULT NULL;

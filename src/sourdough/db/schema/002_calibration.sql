-- Add calibration columns to sesiones

ALTER TABLE sesiones ADD COLUMN fondo_y_pct REAL DEFAULT NULL;
ALTER TABLE sesiones ADD COLUMN tope_y_pct REAL DEFAULT NULL;
ALTER TABLE sesiones ADD COLUMN base_y_pct REAL DEFAULT NULL;
ALTER TABLE sesiones ADD COLUMN izq_x_pct REAL DEFAULT NULL;
ALTER TABLE sesiones ADD COLUMN der_x_pct REAL DEFAULT NULL;
ALTER TABLE sesiones ADD COLUMN is_calibrated INTEGER DEFAULT 0;
ALTER TABLE sesiones ADD COLUMN timelapse_url TEXT;
ALTER TABLE sesiones ADD COLUMN timelapse_file_id TEXT;

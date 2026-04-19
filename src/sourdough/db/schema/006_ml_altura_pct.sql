-- Store the ML model's altura prediction alongside the fused altura.
-- Not part of fusion; kept for comparison/accuracy tracking on the dashboard.

ALTER TABLE mediciones ADD COLUMN ml_altura_pct REAL DEFAULT NULL;

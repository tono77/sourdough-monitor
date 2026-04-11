-- Initial schema: sessions and measurements tables

CREATE TABLE IF NOT EXISTS sesiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    hora_inicio TEXT NOT NULL,
    hora_fin TEXT,
    estado TEXT DEFAULT 'activa',
    num_mediciones INTEGER DEFAULT 0,
    peak_nivel REAL,
    peak_timestamp TEXT,
    notas TEXT
);

CREATE TABLE IF NOT EXISTS mediciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id INTEGER REFERENCES sesiones(id),
    timestamp TEXT NOT NULL,
    foto_path TEXT NOT NULL,
    nivel_pct REAL,
    nivel_px INTEGER,
    burbujas TEXT,
    textura TEXT,
    notas TEXT,
    es_peak INTEGER DEFAULT 0
);

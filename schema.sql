-- MediPass · esquema de base de datos (SQLite)
--
-- Idea central: el principio activo (INN / Denominación Común Internacional)
-- es lo único verdaderamente comparable entre países. La marca comercial
-- cambia por país; el principio activo, no. Por eso es la tabla puente.
--
-- La unidad de equivalencia es principio activo + forma farmacéutica
-- (p.ej. "diclofenaco" + "GEL"), no solo el principio activo: un gel y unas
-- pastillas del mismo principio activo no son intercambiables.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS countries (
  code TEXT PRIMARY KEY,          -- ISO 3166-1 alfa-2: 'ES', 'DE', 'FR'...
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS active_ingredients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  inn_name TEXT NOT NULL UNIQUE,  -- ej. 'dimenhidrinato'; combinaciones: 'dimenhidrinato + cafeína'
  atc_code TEXT,                  -- código ATC si lo tenemos (clasificación internacional OMS)
  category TEXT NOT NULL,         -- 'Salud' | 'Producto sanitario' | 'Higiene' | 'Belleza'
  common_use TEXT                 -- descripción breve en lenguaje natural
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  active_ingredient_id INTEGER NOT NULL REFERENCES active_ingredients(id),
  country_code TEXT NOT NULL REFERENCES countries(code),
  brand_name TEXT NOT NULL,
  requires_prescription INTEGER,  -- 0 = libre, 1 = receta, NULL = desconocido
  source TEXT NOT NULL,           -- 'CIMA_API' | 'manual_seed' | (futuro: 'ANSM_API', 'AIFA_API'...)
  source_ref TEXT,                -- p.ej. nº de registro CIMA, para poder re-consultar/auditar
  verified_at TEXT,               -- fecha ISO de la última verificación contra la fuente
  form TEXT,                      -- forma farmacéutica simplificada (CIMA): 'GEL', 'COMPRIMIDO'...
  dose TEXT,                      -- dosis tal como la da la fuente, p.ej. '50/50 mg/mg'
  composition TEXT,               -- composición legible, p.ej. 'dimenhidrinato 50 mg + cafeina 50 mg'
  atc_code TEXT,                  -- ATC más específico del producto (p.ej. 'R06AA52')
  atc_group TEXT,                 -- grupo terapéutico (ATC nivel 3) en texto
  photo_url TEXT,                 -- foto del producto, si la fuente la ofrece
  UNIQUE(active_ingredient_id, country_code, brand_name)
);

CREATE INDEX IF NOT EXISTS idx_products_ingredient ON products(active_ingredient_id);
CREATE INDEX IF NOT EXISTS idx_products_country ON products(country_code);

-- Vista de conveniencia: para una búsqueda "dame el equivalente de X en el país Y".
-- Se recrea siempre (DROP + CREATE) para que este archivo se pueda volver a
-- ejecutar tras añadir columnas a products.
DROP VIEW IF EXISTS equivalences;
CREATE VIEW equivalences AS
SELECT
  ai.inn_name,
  ai.category,
  ai.common_use,
  p.country_code,
  c.name AS country_name,
  p.brand_name,
  p.requires_prescription,
  p.source,
  p.source_ref,
  p.form,
  p.dose,
  p.composition,
  p.atc_code,
  p.atc_group,
  p.photo_url
FROM products p
JOIN active_ingredients ai ON ai.id = p.active_ingredient_id
JOIN countries c ON c.code = p.country_code;

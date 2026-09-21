-- Países v1
INSERT OR IGNORE INTO countries (code, name) VALUES
  ('ES', 'España'),
  ('DE', 'Alemania'),
  ('FR', 'Francia'),
  ('IT', 'Italia'),
  ('PT', 'Portugal'),
  ('UK', 'Reino Unido');

-- Principios activos base (los mismos 6 casos de las notas originales,
-- ahora como fila única por ingrediente en vez de por producto).
-- Los nombres de diclofenaco y clorhexidina coinciden con el principio
-- activo que usa CIMA (sin concentración: la dosis es del producto).
-- Los principios activos de España los crea fetch_cima.py a partir de CIMA.
INSERT OR IGNORE INTO active_ingredients (inn_name, atc_code, category, common_use) VALUES
  ('docusato sódico',      'S02AA', 'Salud',              'Ablandar y eliminar la cera del oído'),
  ('dimenhidrinato',       'R06AA', 'Salud',              'Prevención de mareo en viajes'),
  ('diclofenaco',          'M02AA', 'Salud',              'Dolor e inflamación muscular/articular localizada'),
  ('apósito hidrocoloide (cicatrizante)', NULL, 'Producto sanitario', 'Heridas leves, protección y cicatrización'),
  ('apósito hidrocoloide (ampollas)',     NULL, 'Producto sanitario', 'Protección y curación de ampollas por rozadura'),
  ('clorhexidina',         'A01AB', 'Higiene',            'Higiene y alivio de aftas/llagas bucales');

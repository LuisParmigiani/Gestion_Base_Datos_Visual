-- 004_corridas.sql — varias extracciones por comprobante, para poder compararlas.
--
-- La 003 guardaba UNA extracción por comprobante en `comprobante.extraccion_ia`.
-- Eso alcanza para corregir, pero no para la pregunta que importa: ¿mejoró el
-- modelo entre una corrida y la siguiente? Para eso hacen falta todas.
--
-- Idempotente, como la 003.

BEGIN;

-- Una corrida = un modelo + un prompt + (quizá) un adaptador LoRA.
-- La descripción y `cambio_respecto_de` son para la pantalla de comparación:
-- un número sin la explicación de qué se cambió no sirve para decidir nada.
CREATE TABLE IF NOT EXISTS corrida (
  nombre              TEXT PRIMARY KEY,
  descripcion         TEXT NOT NULL,
  modelo              TEXT NOT NULL,
  prompt              TEXT,
  adaptador           TEXT,
  cambio_respecto_de  TEXT REFERENCES corrida(nombre),
  que_cambio          TEXT,
  creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Lo que el modelo contestó, crudo. NUNCA se corrige acá: la corrección vive en
-- las columnas tipadas de `comprobante`. Si se pisara, no habría contra qué
-- medir y toda la comparación dejaría de significar nada.
CREATE TABLE IF NOT EXISTS extraccion (
  id             SERIAL PRIMARY KEY,
  comprobante_id INTEGER NOT NULL REFERENCES comprobante(id) ON DELETE CASCADE,
  corrida        TEXT    NOT NULL REFERENCES corrida(nombre),
  campos         JSONB   NOT NULL,
  segundos       NUMERIC(8,2),
  creado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (comprobante_id, corrida)
);

CREATE INDEX IF NOT EXISTS extraccion_por_corrida ON extraccion (corrida);

-- Cuál de las corridas sembró las columnas tipadas del comprobante. Es contra
-- esa que se compara la corrección humana.
ALTER TABLE comprobante ADD COLUMN IF NOT EXISTS corrida_base TEXT REFERENCES corrida(nombre);

-- Migrar lo que la 003 dejó en `extraccion_ia` y sacar la columna: dos lugares
-- con la misma verdad es como se cuelan los errores silenciosos.
INSERT INTO corrida (nombre, descripcion, modelo)
SELECT 'sintetico', 'Etiquetas exactas del generador ia/generar.py. No es una extracción: es la verdad por construcción, para entrenar.', 'ninguno'
WHERE EXISTS (SELECT 1 FROM comprobante WHERE extraccion_ia IS NOT NULL)
ON CONFLICT (nombre) DO NOTHING;

INSERT INTO extraccion (comprobante_id, corrida, campos)
SELECT id, 'sintetico', extraccion_ia FROM comprobante WHERE extraccion_ia IS NOT NULL
ON CONFLICT (comprobante_id, corrida) DO NOTHING;

UPDATE comprobante SET corrida_base = 'sintetico'
WHERE extraccion_ia IS NOT NULL AND corrida_base IS NULL;

ALTER TABLE comprobante DROP CONSTRAINT IF EXISTS revisado_exige_extraccion;
ALTER TABLE comprobante DROP COLUMN IF EXISTS extraccion_ia;

ALTER TABLE comprobante
  ADD CONSTRAINT revisado_exige_corrida
  CHECK (revisado_en IS NULL OR corrida_base IS NOT NULL);

COMMIT;

-- 003_revision.sql — lo que la pantalla de revisión humana necesita.
--
-- Corre sobre una base que ya tiene la 001 y la 002:  pnpm db:migrar
--
-- A diferencia de la 001 y la 002, esta migración ES idempotente: se puede
-- correr dos veces sin romper. Las anteriores no lo son (`ADD COLUMN` pelado),
-- así que `pnpm db:migrar` falla si se lo vuelve a correr sobre la base real.

BEGIN;

-- 1. Lo que dijo la IA, tal cual, para siempre.
--    Las columnas tipadas (monto, fecha, cuit_emisor, …) guardan la VERDAD
--    corregida por una persona. Esta guarda el crudo del modelo y no se pisa
--    nunca. Sin eso, corregir un campo destruye la evidencia de que el modelo
--    lo había sacado mal, y F7/F10 dejan de poder medirse.
ALTER TABLE comprobante ADD COLUMN IF NOT EXISTS extraccion_ia JSONB;

-- 2. Cuándo lo confirmó una persona. NULL = todavía nadie lo miró.
ALTER TABLE comprobante ADD COLUMN IF NOT EXISTS revisado_en TIMESTAMPTZ;

-- QUÉ CAMPOS ESTABAN MAL NO SE GUARDA: sale de comparar las columnas tipadas
-- contra `extraccion_ia`. Mismo criterio que 'sin_comprobante' en la 001 — no
-- se guarda lo que se puede preguntar. La query es:
--
--   SELECT id FROM comprobante
--   WHERE revisado_en IS NOT NULL
--     AND monto::text IS DISTINCT FROM (extraccion_ia->>'monto');

-- 3. Un comprobante revisado tiene que tener contra qué comparar la corrección.
ALTER TABLE comprobante DROP CONSTRAINT IF EXISTS revisado_exige_extraccion;
ALTER TABLE comprobante
  ADD CONSTRAINT revisado_exige_extraccion
  CHECK (revisado_en IS NULL OR extraccion_ia IS NOT NULL);

COMMIT;

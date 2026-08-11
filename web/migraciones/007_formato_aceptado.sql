-- 007_formato_aceptado.sql — "ya lo miré: el comprobante dice eso".
--
-- Corre sobre una base que ya tiene la 001 a la 006:
--   psql -v ON_ERROR_STOP=1 -d conciliador -f migraciones/007_formato_aceptado.sql
-- Es idempotente.
--
-- /revisar marca los comprobantes cuya verdad tiene una forma imposible: un CUIT
-- que no da 11 dígitos, un CBU/CVU que no da 22, o el texto "null" guardado como
-- si fuera un valor. Medido sobre los 51 revisados a mano: 22 quedan marcados, y
-- entre ellos hay errores reales — 9 con el CUIT del receptor mal y uno con un
-- CBU guardado en el campo del CUIT.
--
-- Pero un largo raro NO es siempre un error: si el comprobante muestra el número
-- cortado o enmascarado, lo que está guardado es exactamente lo que hay que
-- guardar. Sin esta columna esos casos volverían a aparecer marcados para
-- siempre y la lista de "con dudas" nunca llegaría a cero, que es lo único que
-- la hace útil.
--
-- Es una marca del comprobante entero y no de cada campo: son 22 casos y una
-- tabla campo-por-campo sería más máquina que problema. Si algún día hace falta
-- el detalle, la respuesta es una tabla aparte, no partir esta columna.

BEGIN;

ALTER TABLE comprobante ADD COLUMN IF NOT EXISTS formato_aceptado_en TIMESTAMPTZ;

COMMENT ON COLUMN comprobante.formato_aceptado_en IS
  'Cuándo una persona confirmó que la forma rara de algún campo es la correcta '
  '(el comprobante muestra el número cortado o enmascarado). NULL = todavía no '
  'lo miró. No lo escribe ningún proceso automático: sale del botón "Guardar '
  'igual" de /revisar/[id].';

COMMIT;

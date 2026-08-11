-- 005_origen_excel.sql — de qué hoja y fila del Excel salió cada movimiento.
--
-- Corre sobre una base que ya tiene la 001 a la 004:  pnpm db:migrar
-- Es idempotente: se puede correr dos veces sin romper.
--
-- Por qué: hasta acá el dato no se guardaba y la pantalla /encontrar lo
-- ESTIMABA contando movimientos de la cuenta. La estimación se corre un lugar
-- por cada fila que el Excel trae y la base no —las 21 repetidas que descarta
-- la huella UNIQUE, y las que no tienen fecha—, así que arrastra el error
-- hacia abajo. Medido sobre el archivo real: la fila mostrada estaba mal en
-- 1196/1298 de SUCESION, 1195/1307 de QUIQUE y 140/217 de MARIELA, con
-- desvíos de hasta 11 filas.
--
-- Quedan NULL hasta que se vuelva a correr `pnpm importar`, que las completa
-- matcheando por huella sin insertar ni borrar nada.

BEGIN;

ALTER TABLE movimiento
  ADD COLUMN IF NOT EXISTS hoja TEXT,     -- el nombre de la pestaña: SUCESION, QUIQUE, MARIELA
  ADD COLUMN IF NOT EXISTS fila INTEGER;  -- 1-based, como lo muestra Excel. La 1 es el encabezado

COMMENT ON COLUMN movimiento.fila IS
  'Fila del .xlsx tal como la numera Excel. Sirve para que una persona vaya a mirarla.';

COMMIT;

-- 008_eleccion.sql — qué fila del extracto eligió una PERSONA para un comprobante.
--
-- Corre sobre una base que ya tiene la 001 a la 007:
--   psql -v ON_ERROR_STOP=1 -d conciliador -f migraciones/008_eleccion.sql
-- Es idempotente.
--
-- Para qué existe: /encontrar propone una fila del extracto por comprobante con
-- la cascada de la empresa (nro de transacción + CUIT → 90%; monto + fecha →
-- 50%). Cuando hay más de un candidato no elige ninguno, porque adivinar entre
-- dos movimientos del mismo importe sería inventar. Acá se guarda cuál eligió
-- una persona, y con eso se puede medir lo único que importa mientras se
-- desarrolla la regla: **cuántas veces el algoritmo acierta solo y cuántas hay
-- que corregirlo a mano**.
--
-- Por qué NO guarda lo que propuso el algoritmo: es determinístico y se
-- recalcula en cada carga de la pantalla. Guardarlo lo dejaría congelado, y el
-- día que se toque la cascada la fila vieja seguiría afirmando lo que la regla
-- decía antes. La comparación sale de cruzar esta tabla con la query en vivo.
--
-- Por qué NO es la tabla `conciliacion`: aquélla la escribe `reconciliar()` con
-- `motor.ts`, que cruza por `cuenta.cbu` y hoy devuelve `no_verificable` en los
-- 69 porque las tres cuentas lo tienen en NULL. Son dos algoritmos distintos y
-- mezclarlos haría imposible saber cuál produjo cada fila.
--
-- ⚠️ ES TEMPORAL, a propósito. Cuando `motor.ts` se reescriba con esta cascada
-- (lo manda la re-especificación), esto se va con un DROP TABLE y las
-- decisiones humanas pasan a `conciliacion.decidido_por = 'persona'`, que ya
-- existe y que `reconciliar()` ya respeta.

BEGIN;

CREATE TABLE IF NOT EXISTS eleccion (
  comprobante_id INTEGER PRIMARY KEY REFERENCES comprobante(id) ON DELETE CASCADE,
  movimiento_id  INTEGER NOT NULL REFERENCES movimiento(id),
  elegido_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
  nota           TEXT
);

-- Una fila del extracto es un movimiento de plata que ocurrió una sola vez: si
-- dos comprobantes la reclaman, uno de los dos está mal y hay que verlo, no
-- resolverlo en silencio. Es el mismo criterio del índice único que ya tiene
-- `conciliacion.movimiento_id`.
CREATE UNIQUE INDEX IF NOT EXISTS eleccion_movimiento_unico
  ON eleccion (movimiento_id);

COMMENT ON TABLE eleccion IS
  'Qué fila del extracto eligió una PERSONA para un comprobante, cuando la '
  'cascada de /encontrar dejó más de un candidato. Temporal: se borra cuando '
  'motor.ts absorba la cascada.';

COMMIT;

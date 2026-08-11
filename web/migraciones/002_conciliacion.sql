-- 002_conciliacion.sql — lo que F1 dejó abierto y F4 obligó a resolver.
--
-- Corre sobre una base que ya tiene la 001:  pnpm db:migrar

BEGIN;

-- 1. Un comprobante tiene UN veredicto vigente, no un historial de veredictos.
--    Sin esto, cada corrida del motor apila una fila más por comprobante.
--    El historial que importa es el de las decisiones humanas, y eso lo
--    guardan `decidido_por` y `decidido_en` de la fila vigente.
CREATE UNIQUE INDEX conciliacion_comprobante_unico ON conciliacion (comprobante_id);

-- 2. El movimiento que un duplicado RECLAMA, sin llegar a quedárselo.
--    `movimiento_id` no sirve: su índice único —el que hace imposible el doble
--    cobro— impide justamente que dos comprobantes lo apunten. Sin esta
--    columna, un duplicado no puede decir con qué chocó.
ALTER TABLE conciliacion
  ADD COLUMN movimiento_pretendido INTEGER REFERENCES movimiento(id);

-- 3. Los candidatos de un ambiguo, para la pantalla que los resuelve.
--    Array nativo y no una tabla puente: se leen y se escriben siempre juntos,
--    nunca se consultan de a uno.
ALTER TABLE conciliacion
  ADD COLUMN candidatos INTEGER[] NOT NULL DEFAULT '{}';

-- Un ambiguo sin candidatos no tiene sentido, y un resuelto no los necesita.
ALTER TABLE conciliacion
  ADD CONSTRAINT candidatos_solo_si_es_ambiguo
  CHECK ((estado = 'ambiguo') = (cardinality(candidatos) > 1));

COMMIT;

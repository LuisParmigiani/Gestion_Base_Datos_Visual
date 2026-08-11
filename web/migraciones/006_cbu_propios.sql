-- 006_cbu_propios.sql — los CBU/CVU que son NUESTROS.
--
-- Corre sobre una base que ya tiene la 001 a la 005:
--   psql -v ON_ERROR_STOP=1 -d conciliador -f migraciones/006_cbu_propios.sql
-- Es idempotente.
--
-- Por qué existe, en palabras del usuario: "nuestro CBU no cambia. Puede que
-- haya alguno nuevo, pero no va a ser lo más normal, por lo que ponelo como
-- dudosa y que vaya a revisión manual".
--
-- Medido sobre los 51 comprobantes revisados a mano: hay 43 con CBU de receptor
-- y **solo 6 valores distintos**. La plata entra siempre a las mismas cuentas.
-- Un CBU de receptor que no esté en esa lista es, casi siempre, un dígito mal
-- leído por la IA — y un dígito mal leído en un CBU no se nota mirando.
--
-- `cuenta.cbu` no alcanza: es uno por cuenta y las cuentas tienen más de uno
-- (CBU y CVU, o cuentas viejas). Por eso una tabla aparte, con la cuenta como
-- referencia OPCIONAL: se puede aprobar un CBU sin saber todavía a cuál va.

BEGIN;

CREATE TABLE IF NOT EXISTS cbu_propio (
  id          SERIAL PRIMARY KEY,
  cbu         TEXT NOT NULL UNIQUE,
  cuenta_id   SMALLINT REFERENCES cuenta(id),
  nota        TEXT,
  agregado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT cbu_22_digitos CHECK (cbu ~ '^[0-9]{22}$')
);

COMMENT ON TABLE cbu_propio IS
  'CBU/CVU propios confirmados por una persona. Un comprobante cuyo receptor no '
  'esté acá queda como transcripción dudosa. NO se siembra desde los datos: '
  'los aprueba el usuario de a uno en /cbu.';

COMMIT;

-- Deliberadamente NO se insertan los 6 CBU que aparecen en los comprobantes.
-- Que la IA haya leído un número muchas veces no lo hace correcto: si leyó mal
-- el mismo dígito en 20 comprobantes del mismo banco, sembrarlo convertiría el
-- error en la regla. Los aprueba una persona en /cbu, que los muestra con su
-- frecuencia para que se decida mirando.

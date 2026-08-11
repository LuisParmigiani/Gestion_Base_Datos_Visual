-- 001_inicial.sql — esquema base del conciliador (F1)
--
-- Corre sobre una base vacía:  pnpm db:migrar
-- Para volver a cero:
--   psql -d conciliador -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
--
-- No lleva DROP TABLE a propósito: en F2 esta base ya tiene 3364 movimientos
-- reales y una migración que borra sola es un accidente esperando el momento.

BEGIN;

-- Las tres cuentas del extracto. Diseñado para N desde el día uno.
CREATE TABLE cuenta (
  id     SMALLSERIAL PRIMARY KEY,
  nombre TEXT    NOT NULL UNIQUE,
  banco  TEXT,
  cbu    TEXT,
  alias  TEXT,
  activa BOOLEAN NOT NULL DEFAULT TRUE
);

-- Cada subida de un Excel. fecha_min/fecha_max definen la COBERTURA:
-- sin eso no se puede distinguir "sospechoso" de "no verificable".
CREATE TABLE extracto_carga (
  id               SERIAL      PRIMARY KEY,
  cuenta_id        SMALLINT    NOT NULL REFERENCES cuenta(id),
  archivo          TEXT        NOT NULL,
  hash_archivo     TEXT        NOT NULL,
  subido_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
  filas_leidas     INTEGER     NOT NULL,
  filas_nuevas     INTEGER     NOT NULL,
  filas_duplicadas INTEGER     NOT NULL,
  fecha_min        DATE,
  fecha_max        DATE
);

-- Una fila del extracto. SALDO no se guarda: es información del banco.
CREATE TABLE movimiento (
  id                SERIAL   PRIMARY KEY,
  cuenta_id         SMALLINT NOT NULL REFERENCES cuenta(id),
  carga_id          INTEGER  NOT NULL REFERENCES extracto_carga(id),
  fecha             DATE     NOT NULL,
  nro_transaccion   TEXT,              -- 1309 presentes / 1286 distintos: no es clave
  descripcion       TEXT     NOT NULL,
  importe_crudo     TEXT     NOT NULL, -- el texto tal como vino: '$ 368.500,00'
  importe           NUMERIC(14,2),     -- NULL en las 29 filas ambiguas. Nunca float
  es_ingreso        BOOLEAN  NOT NULL, -- el signo se conoce aunque el importe sea ambiguo
  requiere_revision BOOLEAN  NOT NULL DEFAULT FALSE,
  cuit_emisor       TEXT,
  coelsa_id         TEXT,
  tipo              TEXT,
  huella            TEXT     NOT NULL UNIQUE,  -- dedup: hash(cuenta,fecha,nro,importe_crudo,descripcion)
  -- Un importe NULL solo se tolera si la fila está marcada para revisar.
  -- Que la base lo garantice evita que un importe fantasma llegue a la conciliación.
  CONSTRAINT importe_nulo_solo_si_se_revisa
    CHECK (importe IS NOT NULL OR requiere_revision)
);

-- La imagen que manda el cliente, con sus 16 campos.
CREATE TABLE comprobante (
  id                SERIAL      PRIMARY KEY,
  archivo           TEXT        NOT NULL,
  hash_imagen       TEXT        NOT NULL UNIQUE, -- detecta el reenvío de la misma imagen
  subido_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
  origen            TEXT        NOT NULL DEFAULT 'manual'
                    CHECK (origen IN ('manual', 'ia')),
  estado_extraccion TEXT        NOT NULL DEFAULT 'pendiente'
                    CHECK (estado_extraccion IN ('pendiente', 'extraido', 'confirmado', 'error')),

  -- los 16 campos, uno por columna: se consultan de a uno en la conciliación
  tipo_operacion    TEXT,
  monto             NUMERIC(14,2),
  moneda            TEXT,
  fecha             DATE,
  hora              TIME,
  nombre_emisor     TEXT,
  cuit_emisor       TEXT,
  cbu_cvu_emisor    TEXT,
  banco_emisor      TEXT,
  nombre_receptor   TEXT,
  cuit_receptor     TEXT,
  cbu_cvu_receptor  TEXT,
  banco_receptor    TEXT,
  concepto          TEXT,
  referencia        TEXT,
  coelsa_id         TEXT
);

-- El veredicto. 'sin_comprobante' no está acá a propósito: es un estado del
-- movimiento, no del comprobante, y sale de una query (movimientos ingresantes
-- que ninguna conciliación referencia). No se guarda lo que se puede preguntar.
CREATE TABLE conciliacion (
  id             SERIAL      PRIMARY KEY,
  comprobante_id INTEGER     NOT NULL REFERENCES comprobante(id) ON DELETE CASCADE,
  movimiento_id  INTEGER     REFERENCES movimiento(id),
  estado         TEXT        NOT NULL
                 CHECK (estado IN ('verificado', 'sospechoso', 'no_verificable',
                                   'duplicado', 'ambiguo')),
  confianza      TEXT        CHECK (confianza IN ('alta', 'media', 'baja')),
  regla          SMALLINT,   -- qué escalón de la cascada resolvió: 1, 2 o 3
  decidido_por   TEXT        NOT NULL DEFAULT 'motor'
                 CHECK (decidido_por IN ('motor', 'persona')),
  decidido_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
  nota           TEXT,
  -- Un veredicto que apunta a un movimiento tiene que decir con qué confianza.
  CONSTRAINT confianza_si_hay_movimiento
    CHECK ((movimiento_id IS NULL) = (confianza IS NULL))
);

-- ESTO es lo que hace imposible el doble cobro. No depende de que el código
-- se acuerde: un movimiento no puede ser reclamado por dos comprobantes.
CREATE UNIQUE INDEX conciliacion_movimiento_unico
  ON conciliacion (movimiento_id)
  WHERE movimiento_id IS NOT NULL;

-- Las tres cuentas del extracto. CBU y alias van vacíos: falta el dato.
-- Sin CBU, en F4 no se puede saber si un comprobante apunta a una cuenta
-- nuestra. No bloquea F2 ni F3.
-- El banco tampoco se inventa: el extracto no lo dice.
INSERT INTO cuenta (nombre) VALUES ('SUCESION'), ('QUIQUE'), ('MARIELA');

COMMIT;

"""Las tres tablas del portal del cliente.

El saldo vive en una columna de `cliente`, no se calcula sumando el libro cada
vez. Es una decisión del usuario: con años de movimientos, recalcular en cada
pantalla se vuelve caro. El precio es que la columna puede despegarse del libro,
y contra eso hay dos guardas:

  1. `registrar_movimiento()` es el ÚNICO camino para mover el saldo, y escribe
     el movimiento y la columna en la misma transacción.
  2. `verificar_saldos.py` recalcula la suma y avisa si alguna no coincide.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Los 16 campos que devuelve la IA, en el orden de `ia/extraer.py:21`. Se repiten
# acá y no se importan de `ia/` para que el portal no dependa del script de
# inferencia para arrancar; si allá se agrega uno, hay que agregarlo acá.
CAMPOS = (
    "tipo_operacion", "monto", "moneda", "fecha", "hora",
    "nombre_emisor", "cuit_emisor", "cbu_cvu_emisor", "banco_emisor",
    "nombre_receptor", "cuit_receptor", "cbu_cvu_receptor", "banco_receptor",
    "concepto", "referencia", "coelsa_id",
)

# El adaptador con el que se lee. Fijo por decisión del usuario: es el mejor
# medido (82,6% en el corte honesto, contra 66,1% del modelo base).
ADAPTADOR = "lora_v4_v2"

# Los cuatro estados de un comprobante. La parte 1 solo escribe PENDIENTE; los
# otros tres los produce el lote del dueño (parte 2) y están acá para que el
# recorrido completo se lea en un solo lugar.
PENDIENTE = "pendiente"  # subido y sin leer, o leído y con fecha que aún no está en el extracto
CONFIRMADO = "confirmado"  # cruzado contra el extracto: sumó el saldo
REVISION_MANUAL = "revision_manual"  # el día está en el extracto pero la fila no apareció
EN_DISPUTA = "en_disputa"  # dos comprobantes reclaman la misma fila; decide el dueño


class Base(DeclarativeBase):
    pass


class Cliente(Base):
    __tablename__ = "cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80))
    apellido: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    cuit: Mapped[str | None] = mapped_column(String(13))
    saldo: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    creado_en: Mapped[datetime] = mapped_column(DateTime, insert_default=func.now())

    comprobantes: Mapped[list["Comprobante"]] = relationship(back_populates="cliente")
    movimientos: Mapped[list["MovimientoCuenta"]] = relationship(back_populates="cliente")

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}"


class Comprobante(Base):
    __tablename__ = "comprobante"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"))
    archivo: Mapped[str] = mapped_column(Text)  # ruta relativa a portal/comprobantes/
    # La escribe el cliente solo si el comprobante no muestra la fecha.
    fecha_declarada: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default=PENDIENTE)
    # Cuántas veces lo leyó el lote. Se frena en 3.
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    # Con cuánta certeza se lo cruzó: 90 o 50 según el escalón de la cascada, y
    # 100 cuando lo eligió el dueño a mano. NULL mientras no esté cruzado.
    confianza: Mapped[int | None] = mapped_column(Integer)
    # Por qué está donde está: se le muestra al dueño en la bandeja.
    motivo: Mapped[str | None] = mapped_column(Text)
    subido_en: Mapped[datetime] = mapped_column(DateTime, insert_default=func.now())

    cliente: Mapped["Cliente"] = relationship(back_populates="comprobantes")
    extracciones: Mapped[list["Extraccion"]] = relationship(back_populates="comprobante")


class MovimientoCuenta(Base):
    """Una línea de la actividad. `monto` lleva signo: + acredita, − descuenta."""

    __tablename__ = "movimiento_cuenta"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"))
    fecha: Mapped[date] = mapped_column(Date)
    concepto: Mapped[str] = mapped_column(Text)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    # Solo lo tienen los movimientos que nacieron de un comprobante confirmado.
    comprobante_id: Mapped[int | None] = mapped_column(ForeignKey("comprobante.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime, insert_default=func.now())

    cliente: Mapped["Cliente"] = relationship(back_populates="movimientos")
    comprobante: Mapped["Comprobante | None"] = relationship()


class MovimientoBanco(Base):
    """Una fila del extracto del banco. Lo que el comprobante tiene que encontrar.

    `comprobante_id` es la marca de "fila tomada", y es **UNIQUE**: la garantía de
    que dos comprobantes no puedan quedarse con la misma transferencia la da
    Postgres, no el código del lote. Un segundo comprobante que intente la misma
    fila choca contra la base, y ese choque ES la señal de disputa.
    """

    __tablename__ = "movimiento_banco"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta: Mapped[str] = mapped_column(String(120))  # el nombre de la hoja del Excel
    fecha: Mapped[date] = mapped_column(Date, index=True)
    nro_transaccion: Mapped[str | None] = mapped_column(String(60), index=True)
    descripcion: Mapped[str] = mapped_column(Text)
    importe_crudo: Mapped[str] = mapped_column(Text)
    # NULL cuando el importe es ambiguo. No se adivina: un importe inventado es
    # una acusación falsa.
    importe: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    es_ingreso: Mapped[bool] = mapped_column(Boolean)
    requiere_revision: Mapped[bool] = mapped_column(Boolean, default=False)
    cuit_emisor: Mapped[str | None] = mapped_column(String(13), index=True)
    coelsa_id: Mapped[str | None] = mapped_column(String(30))
    tipo: Mapped[str | None] = mapped_column(String(30))
    huella: Mapped[str] = mapped_column(String(64), unique=True)
    hoja: Mapped[str | None] = mapped_column(String(120))
    fila: Mapped[int | None] = mapped_column(Integer)
    comprobante_id: Mapped[int | None] = mapped_column(
        ForeignKey("comprobante.id"), unique=True
    )
    # De qué subida vino. Es lo que permite deshacer una carga equivocada entera.
    carga_id: Mapped[int | None] = mapped_column(ForeignKey("carga_extracto.id"), index=True)
    importado_en: Mapped[datetime] = mapped_column(DateTime, insert_default=func.now())

    comprobante: Mapped["Comprobante | None"] = relationship()


class CargaExtracto(Base):
    """Una subida de Excel. Existe para poder mirarla después y para poder deshacerla.

    Una fila por **archivo subido**, no por hoja: cuando el dueño se equivoca de
    archivo quiere deshacer la subida entera, no media.
    """

    __tablename__ = "carga_extracto"

    id: Mapped[int] = mapped_column(primary_key=True)
    archivo: Mapped[str] = mapped_column(Text)  # el nombre que tenía al subirlo
    # SHA-256 del archivo: sirve para avisar "este ya lo subiste" antes de repetir.
    hash_archivo: Mapped[str] = mapped_column(String(64))
    # La cuenta que eligió el dueño, o NULL si se usó el nombre de cada hoja.
    cuenta_forzada: Mapped[str | None] = mapped_column(String(120))
    filas_leidas: Mapped[int] = mapped_column(Integer, default=0)
    filas_nuevas: Mapped[int] = mapped_column(Integer, default=0)
    filas_duplicadas: Mapped[int] = mapped_column(Integer, default=0)
    # El detalle por hoja, tal como lo devolvió el importador.
    resumen: Mapped[dict | None] = mapped_column(JSONB)
    importado_en: Mapped[datetime] = mapped_column(DateTime, insert_default=func.now())


class CbuPropio(Base):
    """Los CBU/CUIT del dueño. Un receptor que no esté acá deja el comprobante en duda.

    ⛔ **No los siembra la IA.** Que haya leído un número veinte veces no lo hace
    correcto: los aprueba una persona. Es la misma regla que en `web/`.
    """

    __tablename__ = "cbu_propio"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Guardado solo con sus dígitos: el extracto no trae guiones y una persona sí.
    valor: Mapped[str] = mapped_column(String(30), unique=True)
    etiqueta: Mapped[str | None] = mapped_column(String(120))
    # 'manual' si lo escribió el dueño, 'propuesto' si salió de un comprobante.
    origen: Mapped[str] = mapped_column(String(20), default="manual")
    aprobado_en: Mapped[datetime | None] = mapped_column(DateTime)
    creado_en: Mapped[datetime] = mapped_column(DateTime, insert_default=func.now())


class Extraccion(Base):
    """Lo que leyó la IA en un intento. Nunca se pisa: es la evidencia de la corrida."""

    __tablename__ = "extraccion"

    id: Mapped[int] = mapped_column(primary_key=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobante.id"))
    intento: Mapped[int] = mapped_column(Integer)  # 1, 2 o 3
    variante: Mapped[str] = mapped_column(String(20))  # original · contraste · escala
    campos: Mapped[dict] = mapped_column(JSONB)  # los 16, como los devolvió el modelo
    adaptador: Mapped[str] = mapped_column(String(40), default=ADAPTADOR)
    creado_en: Mapped[datetime] = mapped_column(DateTime, insert_default=func.now())

    comprobante: Mapped["Comprobante"] = relationship(back_populates="extracciones")


class Correccion(Base):
    """Un campo que la IA leyó mal, con lo que era en realidad. Combustible de reentrenamiento.

    Se guarda **por campo**, no como un texto libre, porque para reentrenar hace
    falta el par (imagen, los 16 campos correctos) que consume `ia/reales.py`.
    Una descripción en prosa no se puede convertir en un ejemplo de entrenamiento;
    un `campo · valor_leido · valor_correcto` sí. `descripcion` queda igual, para
    lo que no entre en ningún campo.

    Cada corrección que el dueño hace en la bandeja —trabajo que hay que hacer de
    todos modos— produce una fila acá. Es la fábrica de datos etiquetados que hoy
    el proyecto no tiene: la verdad de referencia son 58 comprobantes corregidos
    a mano, y es su cuello de botella medido.
    """

    __tablename__ = "correccion"

    id: Mapped[int] = mapped_column(primary_key=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("comprobante.id"))
    campo: Mapped[str] = mapped_column(String(30))  # uno de CAMPOS
    valor_leido: Mapped[str | None] = mapped_column(Text)
    valor_correcto: Mapped[str | None] = mapped_column(Text)
    descripcion: Mapped[str | None] = mapped_column(Text)  # nota libre, opcional
    adaptador: Mapped[str] = mapped_column(String(40), default=ADAPTADOR)
    variante: Mapped[str | None] = mapped_column(String(20))
    creado_en: Mapped[datetime] = mapped_column(DateTime, insert_default=func.now())

    comprobante: Mapped["Comprobante"] = relationship()


def registrar_movimiento(
    sesion,
    cliente: Cliente,
    fecha: date,
    concepto: str,
    monto: Decimal,
    comprobante: Comprobante | None = None,
) -> MovimientoCuenta:
    """Agrega una línea a la actividad y mueve el saldo, en la misma transacción.

    El saldo se incrementa del lado del servidor (`saldo = saldo + :monto`), no
    leyendo el valor en Python y escribiéndolo de vuelta: así dos movimientos
    simultáneos no se pisan.
    """
    # Los dos flush son necesarios y cada uno tapa una trampa distinta:
    #
    #   el de arriba — un cliente recién creado todavía no tiene fila, y sin él
    #   el `saldo + monto` se cuela dentro del INSERT: Postgres rechaza que la
    #   fila se referencie a sí misma ("invalid reference to FROM-clause entry").
    #
    #   el de abajo — dos incrementos pendientes sobre el mismo cliente se pisan
    #   en memoria y sobrevive solo el último. Emitiendo el UPDATE acá, cada
    #   movimiento suma sobre el valor ya guardado. Sigue todo en la transacción
    #   del que llama: un rollback se lleva el movimiento y el saldo juntos.
    sesion.flush()

    movimiento = MovimientoCuenta(
        cliente=cliente,
        fecha=fecha,
        concepto=concepto,
        monto=monto,
        comprobante=comprobante,
    )
    sesion.add(movimiento)
    cliente.saldo = Cliente.saldo + monto
    sesion.flush()
    return movimiento

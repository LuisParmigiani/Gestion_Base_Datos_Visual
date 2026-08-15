"""El lote del dueño: lee los comprobantes pendientes y los cruza contra el extracto.

    ia/.venv/bin/python -m portal.lote [--incluir-50]

El recorrido, tal como lo dictó el usuario:

    hasta 3 intentos, con la imagen VARIADA en cada uno:
        ¿cruza contra una fila del extracto?
          sí, y la fila está libre   → confirmado      (suma el saldo, toma la fila)
          sí, y la fila ya es de otro → en_disputa      (elige el dueño)
          sí, pero hay varias libres  → revision_manual (la cascada no adivina)
          no                          → siguiente intento

    agotados los 3, y si la fecha salió IGUAL en los tres:
        ¿hay alguna fila del extracto de ese día?
          sí  → revision_manual   (el día está cargado y la fila no aparece)
          no  → sigue pendiente   (el dueño todavía no subió ese período)
    si la fecha cambió entre intentos → revision_manual

⚠️ **El modelo es determinista** (`temperature=0.0`): leer la misma imagen tres
veces devuelve tres veces lo mismo. Por eso cada intento ve una imagen distinta
—contraste, escala—, que además ataca donde está el techo medido: el LoRA no
toca la parte visual, así que lo que falla es la lectura, no la escritura.

Se recorre **variante por variante y no comprobante por comprobante**: así el
modelo se carga 3 veces en total y no 3 veces por comprobante.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps
from sqlalchemy import exists, select

from portal import archivos
from portal.cascada import candidatos, fecha_de_texto, monto_de_texto, solo_digitos
from portal.db import Sesion
from portal.modelos import (
    ADAPTADOR,
    CONFIRMADO,
    EN_DISPUTA,
    PENDIENTE,
    REVISION_MANUAL,
    CbuPropio,
    Comprobante,
    Extraccion,
    MovimientoBanco,
    registrar_movimiento,
)

RAIZ = Path(__file__).resolve().parent.parent
PYTHON_IA = RAIZ / "ia" / ".venv" / "bin" / "python"
EXTRAER = RAIZ / "ia" / "extraer.py"
CHECKPOINT = RAIZ / "ia" / "checkpoints" / ADAPTADOR

VARIANTES = ("original", "contraste", "escala")

# ⚠️ El modelo gasta UN TOKEN CADA 28×28 px, sin achicar a un tamaño fijo: los
# tokens escalan con el ÁREA. Agrandar el lado 1,5× son 2,25 veces más tokens.
#
# Medido el 15-ago con una foto real de 1320×2782 (≈4.653 tokens): en su tamaño
# original anda, y al 1,5× (≈10.430 tokens) mlx intenta reservar 57 GB y el
# proceso muere. El tope se aplica a TODAS las variantes y no solo a la que
# agranda: una foto de celular moderna, sola y sin tocar, ya se pasa.
TOKENS_MAXIMOS = 4_000

# Lo que la pantalla del dueño consulta mientras el lote corre. Un dict de módulo
# alcanza: es una app local de un solo proceso y un solo dueño.
ESTADO: dict = {
    "corriendo": False, "variante": None, "hechos": 0, "total": 0,
    "resumen": None, "error": None,
}


class SinCbuPropio(Exception):
    """No hay contra qué verificar el receptor. El lote no arranca."""


def tokens_de(imagen: Image.Image) -> int:
    """Cuántos tokens le va a costar esta imagen al modelo. Uno cada 28×28 px."""
    return (imagen.width // 28) * (imagen.height // 28)


def _a_tokens(imagen: Image.Image, objetivo: int) -> Image.Image:
    """Redimensiona para que la imagen cueste ~`objetivo` tokens, y **nunca más**.

    Agranda o achica según haga falta. El ajuste final es necesario porque los
    tokens se cuentan por bloques enteros de 28 px: un solo cálculo con la raíz
    del cociente puede pasarse (una foto de 400×300 llevada a 4.000 daba 4.332).
    """
    tokens = tokens_de(imagen)
    if tokens == 0:
        return imagen
    factor = (objetivo / tokens) ** 0.5
    imagen = imagen.resize(
        (max(28, int(imagen.width * factor)), max(28, int(imagen.height * factor))),
        Image.LANCZOS,
    )
    while tokens_de(imagen) > objetivo and imagen.width > 56:
        imagen = imagen.resize(
            (int(imagen.width * 0.97), int(imagen.height * 0.97)), Image.LANCZOS
        )
    return imagen


def variar(origen: Path, variante: str, destino: Path) -> Path:
    """Escribe la imagen modificada y devuelve su ruta.

    Las tres son a propósito baratas: si las tres fallan parejo, el problema es
    de lectura visual y no lo arregla ninguna cuarta variante.

    Ninguna puede pasarse de `TOKENS_MAXIMOS` — ver el comentario de arriba, que
    es el error que mató la primera corrida real.
    """
    with Image.open(origen) as imagen:
        imagen = imagen.convert("RGB")

        # El techo, para las tres. Una foto de celular sola ya se pasa.
        if tokens_de(imagen) > TOKENS_MAXIMOS:
            imagen = _a_tokens(imagen, TOKENS_MAXIMOS)

        if variante == "contraste":
            imagen = ImageEnhance.Sharpness(ImageOps.autocontrast(imagen)).enhance(2.0)
        elif variante == "escala":
            # Tiene que ver una resolución DISTINTA de la de `original`, o las
            # dos lecturas son idénticas y la relectura no aporta nada: el modelo
            # corre con `temperature=0.0`, así que la misma imagen da la misma
            # respuesta siempre. Si la foto entra holgada, agranda hasta el tope;
            # si ya estaba contra el tope, achica a la mitad.
            actuales = tokens_de(imagen)
            objetivo = TOKENS_MAXIMOS if actuales < TOKENS_MAXIMOS // 2 else actuales // 2
            imagen = _a_tokens(imagen, objetivo)

        imagen.save(destino, format="JPEG", quality=95)
    return destino


class FalloDeLectura(Exception):
    """`extraer.py` no pudo leer. El mensaje trae las últimas líneas de su error."""


def leer(rutas: list[Path]) -> list[dict]:
    """Corre `ia/extraer.py` sobre las imágenes y devuelve los campos de cada una.

    Una sola invocación para todas: cargar el modelo es lo caro, leer no.
    Siempre con `lora_v4_v2` — el mejor medido, y fijo por decisión del usuario.

    Si el proceso muere, el error **no se traga**: sube con las últimas líneas de
    su stderr adentro. Antes esto reventaba en silencio y el dueño veía el
    comprobante en `pendiente` sin ninguna explicación.
    """
    if not rutas:
        return []
    salida = subprocess.run(
        [str(PYTHON_IA), str(EXTRAER), "--adaptador", str(CHECKPOINT), *map(str, rutas)],
        capture_output=True,
        text=True,
    )
    if salida.returncode != 0:
        ultimas = [l for l in salida.stderr.strip().splitlines() if l.strip()][-3:]
        raise FalloDeLectura(
            f"`extraer.py` terminó con código {salida.returncode}. " + " · ".join(ultimas)
        )
    return [json.loads(linea) for linea in salida.stdout.splitlines() if linea.strip()]


def _receptores(campos: dict) -> set[str]:
    """El CBU y el CUIT del receptor, por sus dígitos. Lo que identifica la cuenta."""
    return {
        solo_digitos(campos.get("cbu_cvu_receptor")),
        solo_digitos(campos.get("cuit_receptor")),
    } - {None}


def _es_receptor_propio(sesion, campos: dict) -> bool:
    """¿La plata cayó en una cuenta del dueño?

    Un receptor que no esté en `cbu_propio` **no se rechaza**: se relee, y si se
    sostiene en los tres intentos, se le pregunta al dueño si es una cuenta suya
    nueva. Que la IA haya leído un número tres veces no lo hace correcto, pero
    que lo lea tres veces distinto sí lo hace sospechoso.
    """
    receptores = _receptores(campos)
    if not receptores:
        return False
    return sesion.scalar(
        select(exists().where(CbuPropio.valor.in_(receptores),
                              CbuPropio.aprobado_en.is_not(None)))
    )


def _resolver(sesion, comprobante, campos, movimientos, incluir_50) -> bool:
    """Intenta cerrar el comprobante con lo que se leyó. True si quedó resuelto."""
    if not _es_receptor_propio(sesion, campos):
        return False  # se relee; si se sostiene, lo decide el dueño al final

    encontrados = candidatos(campos, movimientos, incluir_50)
    if not encontrados:
        return False

    por_id = {m.id: m for m in movimientos}
    confianza_de = dict(encontrados)
    libres = [i for i, _ in encontrados if por_id[i].comprobante_id is None]

    if len(libres) > 1:
        comprobante.estado = REVISION_MANUAL
        comprobante.motivo = (
            f"Hay {len(libres)} filas del extracto que coinciden. La regla no elige "
            "entre transferencias iguales: elegí vos cuál es."
        )
        return True

    if not libres:
        comprobante.estado = EN_DISPUTA
        comprobante.motivo = (
            "La fila que le corresponde ya está asignada a otro comprobante. "
            "Si los dos parecen correctos, uno de los dos está mal leído."
        )
        return True

    fila = por_id[libres[0]]
    # El importe sale del EXTRACTO, no de lo que leyó la IA: ante cualquier duda
    # gana el extracto (regla 3 del proyecto).
    fila.comprobante_id = comprobante.id
    comprobante.estado = CONFIRMADO
    comprobante.confianza = confianza_de[fila.id]
    comprobante.motivo = None
    registrar_movimiento(
        sesion,
        comprobante.cliente,
        fila.fecha,
        f"Transferencia acreditada — {fila.descripcion[:80]}",
        fila.importe,
        comprobante,
    )
    return True


def _cerrar_sin_cruce(sesion, comprobante, fechas_leidas, receptores_leidos) -> None:
    """Los 3 intentos pasaron y no cruzó. Decide entre esperar y molestar al dueño."""
    # Primero el CBU: si la plata no cayó en una cuenta conocida, eso explica
    # todo lo demás y es lo que el dueño tiene que responder.
    sostenidos = set.intersection(*receptores_leidos) if receptores_leidos else set()
    # Solo los que NO son del dueño: un receptor propio sostenido es lo normal,
    # y avisar de él escondería el motivo verdadero por el que no cruzó.
    ajenos = sostenidos - set(sesion.scalars(
        select(CbuPropio.valor).where(CbuPropio.valor.in_(sostenidos or {""}),
                                      CbuPropio.aprobado_en.is_not(None))
    ))
    if ajenos:
        comprobante.estado = REVISION_MANUAL
        comprobante.motivo = (
            f"El receptor {sorted(ajenos)[0]} no está entre tus cuentas, y se leyó "
            "igual en los tres intentos. ¿Es una cuenta tuya nueva? Si lo es, agregala "
            "en /admin/cbu y volvé a correr el lote."
        )
        return

    distintas = {f for f in fechas_leidas if f is not None}

    if len(distintas) != 1:
        comprobante.estado = REVISION_MANUAL
        comprobante.motivo = (
            "La fecha no se sostiene entre lecturas, así que no se puede saber de "
            "qué día es. Miralo vos."
        )
        return

    fecha = distintas.pop()
    hay_ese_dia = sesion.scalar(
        select(exists().where(MovimientoBanco.fecha == fecha))
    )
    if hay_ese_dia:
        comprobante.estado = REVISION_MANUAL
        comprobante.motivo = (
            f"El {fecha:%d/%m/%Y} está cargado en el extracto y esta transferencia "
            "no aparece. Puede estar mal leída o no ser de esta cuenta."
        )
    else:
        comprobante.estado = PENDIENTE
        comprobante.motivo = (
            f"Todavía no hay movimientos del {fecha:%d/%m/%Y} en el extracto. "
            "Se reintenta cuando cargues ese período."
        )


def ultimas_lecturas(sesion, comprobante_id: int) -> list[Extraccion]:
    """Las extracciones de la ÚLTIMA corrida del lote, en orden.

    Correr el lote dos veces deja dos series de intentos 1-2-3 para el mismo
    comprobante. Mezclarlas haría, por ejemplo, que el diagnóstico dijera «la
    fecha cambió entre lecturas» comparando corridas distintas, que es una
    conclusión falsa. La última corrida es el bloque que arranca en el último
    `intento == 1`.
    """
    todas = list(sesion.scalars(
        select(Extraccion).where(Extraccion.comprobante_id == comprobante_id)
        .order_by(Extraccion.id)
    ))
    for posicion in range(len(todas) - 1, -1, -1):
        if todas[posicion].intento == 1:
            return todas[posicion:]
    return todas


def diagnostico(sesion, comprobante, incluir_50: bool = False) -> list[dict]:
    """Por qué este comprobante está donde está, paso por paso.

    Se recalcula cada vez en vez de guardarse: así refleja el estado de HOY —si
    entre medio cargaste el extracto o un CBU, el diagnóstico cambia solo— y no
    una frase congelada que ya no es cierta.

    Cada paso es `{paso, estado, detalle}` con estado `ok`, `falla` o `info`.
    """
    pasos: list[dict] = []
    extracciones = ultimas_lecturas(sesion, comprobante.id)

    # 1 · ¿lo leyó?
    if not extracciones:
        pasos.append({
            "paso": "Lectura",
            "estado": "falla",
            "detalle": comprobante.motivo or "El lote todavía no lo leyó. Corré el lote.",
        })
        return pasos

    pasos.append({
        "paso": "Lectura",
        "estado": "ok",
        "detalle": f"Se leyó {len(extracciones)} vez/veces con {ADAPTADOR}, en las variantes "
                   + ", ".join(e.variante for e in extracciones) + ".",
    })

    ultima = extracciones[-1].campos or {}
    monto = monto_de_texto(ultima.get("monto"))
    fecha = fecha_de_texto(ultima.get("fecha"))

    # 2 · ¿qué entendió, y se sostuvo entre intentos?
    leidos = []
    for etiqueta, clave in [("monto", "monto"), ("fecha", "fecha"),
                            ("CUIT del emisor", "cuit_emisor"), ("referencia", "referencia")]:
        valores = {str(e.campos.get(clave)) for e in extracciones if e.campos}
        marca = "" if len(valores) == 1 else f"  ⚠️ cambió entre lecturas: {' / '.join(sorted(valores))}"
        leidos.append(f"{etiqueta}: {ultima.get(clave) or '—'}{marca}")
    pasos.append({
        "paso": "Qué entendió",
        "estado": "info" if all("⚠️" not in l for l in leidos) else "falla",
        "detalle": " · ".join(leidos),
    })

    # 3 · ¿la plata cayó en una cuenta tuya?
    receptores = _receptores(ultima)
    propios = set(sesion.scalars(select(CbuPropio.valor).where(
        CbuPropio.aprobado_en.is_not(None))))
    if not propios:
        pasos.append({"paso": "Receptor", "estado": "falla",
                      "detalle": "No hay ningún CBU propio cargado, así que no hay contra qué "
                                 "verificar. Cargalos en /admin/cbu."})
    elif receptores & propios:
        pasos.append({"paso": "Receptor", "estado": "ok",
                      "detalle": f"Cayó en una cuenta tuya ({sorted(receptores & propios)[0]})."})
    else:
        leido = ", ".join(sorted(receptores)) or "no leyó ningún CBU ni CUIT de receptor"
        pasos.append({"paso": "Receptor", "estado": "falla",
                      "detalle": f"El receptor que leyó ({leido}) no está entre tus cuentas. "
                                 "Si es una cuenta tuya, agregala en /admin/cbu."})

    # 4 · la cascada, escalón por escalón
    movimientos = list(sesion.scalars(select(MovimientoBanco)))
    encontrados = candidatos(ultima, movimientos, incluir_50)
    por_id = {m.id: m for m in movimientos}
    if not encontrados:
        faltan = [n for n, v in [("monto", monto), ("fecha", fecha),
                                 ("CUIT", solo_digitos(ultima.get("cuit_emisor")))] if not v]
        motivo = (f"No se pudo cruzar porque no se entendió: {', '.join(faltan)}."
                  if faltan else
                  "Ninguna fila del extracto coincide con esos datos.")
        pasos.append({"paso": "Cruce con el extracto", "estado": "falla", "detalle": motivo})
    else:
        libres = [i for i, _ in encontrados if por_id[i].comprobante_id is None]
        detalle = "; ".join(
            f"fila {por_id[i].fila} de {por_id[i].hoja} ({c}%)"
            + ("" if por_id[i].comprobante_id is None
               else f" — ya es del comprobante {por_id[i].comprobante_id}")
            for i, c in encontrados
        )
        pasos.append({
            "paso": "Cruce con el extracto",
            "estado": "ok" if len(libres) == 1 else "falla",
            "detalle": f"{len(encontrados)} coincidencia(s), {len(libres)} libre(s): {detalle}",
        })

    # 5 · ¿el extracto llega hasta ese día?
    if fecha:
        hay = sesion.scalar(select(exists().where(MovimientoBanco.fecha == fecha)))
        pasos.append({
            "paso": "El día en el extracto",
            "estado": "ok" if hay else "info",
            "detalle": (f"Hay movimientos del {fecha:%d/%m/%Y} cargados."
                        if hay else
                        f"No hay ningún movimiento del {fecha:%d/%m/%Y}. Puede que todavía no "
                        "hayas subido ese período: se reintenta cuando lo cargues."),
        })
    return pasos


def correr(incluir_50: bool = False) -> dict:
    """Corre el lote entero. Devuelve el resumen por estado.

    **Nunca deja al dueño sin explicación.** Cualquier falla queda en
    `ESTADO['error']`, que la pantalla muestra, y en el `motivo` de cada
    comprobante afectado. Corriendo en segundo plano, una excepción que sube
    hasta el final no la ve nadie.
    """
    ESTADO.update(corriendo=True, variante=None, hechos=0, total=0,
                  resumen=None, error=None)
    try:
        with Sesion() as sesion:
            if not sesion.scalar(
                select(exists().where(CbuPropio.aprobado_en.is_not(None)))
            ):
                raise SinCbuPropio(
                    "No hay ningún CBU propio aprobado. Sin eso no se puede verificar "
                    "que la plata haya caído en una cuenta tuya, y acreditar sin ese "
                    "chequeo es sumarle saldo a alguien por una transferencia que "
                    "pudo ir a cualquier lado. Cargalos en /admin/cbu."
                )

            pendientes = list(sesion.scalars(
                select(Comprobante).where(Comprobante.estado == PENDIENTE)
                .order_by(Comprobante.id)
            ))
            movimientos = list(sesion.scalars(select(MovimientoBanco)))
            ESTADO["total"] = len(pendientes)

            fechas: dict[int, list[date | None]] = {c.id: [] for c in pendientes}
            receptores: dict[int, list[set[str]]] = {c.id: [] for c in pendientes}
            quedan = pendientes
            abortado = False

            with tempfile.TemporaryDirectory() as taller:
                for numero, variante in enumerate(VARIANTES, start=1):
                    if not quedan:
                        break
                    ESTADO["variante"] = variante

                    rutas, deben = [], []
                    for comprobante in quedan:
                        original = archivos.CARPETA / comprobante.archivo
                        if not original.exists():
                            comprobante.estado = REVISION_MANUAL
                            comprobante.motivo = "Falta el archivo de la imagen."
                            continue
                        destino = Path(taller) / f"{comprobante.id}_{variante}.jpg"
                        rutas.append(variar(original, variante, destino))
                        deben.append(comprobante)

                    try:
                        lecturas = leer(rutas)
                    except FalloDeLectura as falla:
                        # El lote no puede seguir con esta variante, pero lo que
                        # ya se leyó vale: se guarda y se dice qué pasó.
                        ESTADO["error"] = str(falla)
                        for comprobante in deben:
                            comprobante.motivo = (
                                f"La lectura falló en la variante «{variante}». {falla}"
                            )
                        sesion.commit()
                        abortado = True
                        break

                    siguen = []
                    for comprobante, leido in zip(deben, lecturas):
                        campos = leido.get("campos") or {}
                        comprobante.intentos = numero
                        sesion.add(Extraccion(
                            comprobante_id=comprobante.id,
                            intento=numero,
                            variante=variante,
                            campos=campos,
                        ))
                        fechas[comprobante.id].append(fecha_de_texto(campos.get("fecha")))
                        receptores[comprobante.id].append(_receptores(campos))

                        if _resolver(sesion, comprobante, campos, movimientos, incluir_50):
                            ESTADO["hechos"] += 1
                        else:
                            siguen.append(comprobante)
                    quedan = siguen
                    # Se guarda al cerrar cada vuelta: leer es lo caro —minutos de
                    # modelo— y un fallo en la vuelta siguiente no puede borrar lo
                    # que ya costó. Pasó el 15-ago: reventó la tercera variante y
                    # se perdieron las dos lecturas buenas.
                    sesion.commit()

            # Si la lectura se cayó, estos comprobantes ya tienen su explicación
            # y es mejor que cualquier conclusión sacada de datos incompletos:
            # decir "no aparece en el extracto" cuando en realidad no se pudo
            # leer sería mentirle al dueño.
            if not abortado:
                for comprobante in quedan:
                    _cerrar_sin_cruce(
                        sesion, comprobante, fechas[comprobante.id],
                        receptores[comprobante.id],
                    )
                    ESTADO["hechos"] += 1

            resumen = {estado: 0 for estado in
                       (CONFIRMADO, EN_DISPUTA, REVISION_MANUAL, PENDIENTE)}
            for comprobante in pendientes:
                resumen[comprobante.estado] += 1
            sesion.commit()

        ESTADO["resumen"] = resumen
        return resumen
    except SinCbuPropio as falta:
        ESTADO["error"] = str(falta)
        raise
    except Exception as falla:
        # Corriendo en segundo plano nadie ve esto: si no queda registrado acá,
        # el dueño ve los comprobantes sin cambiar y ninguna explicación.
        ESTADO["error"] = f"{type(falla).__name__}: {falla}"
        raise
    finally:
        ESTADO["corriendo"] = False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incluir-50", action="store_true",
                        help="acredita también lo que solo cruza por monto + fecha")
    try:
        for estado, cuantos in correr(parser.parse_args().incluir_50).items():
            print(f"  {estado:<18} {cuantos}")
    except SinCbuPropio as falta:
        sys.exit(f"\n{falta}\n")

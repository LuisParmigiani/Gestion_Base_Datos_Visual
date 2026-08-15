"""El panel del dueño: el negocio, el extracto, el lote y lo que hay que decidir a mano.

Sin contraseña, por decisión del usuario. **Esto no es seguridad**: cualquiera
que escriba /admin recarga saldos y ve a todos los clientes. Corre en una sola
máquina; el día que salga de ahí hace falta login de verdad.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Text, delete, func, or_, select

from portal import exportar, importar, lote
from portal.cascada import monto_de_texto, solo_digitos
from portal.db import Sesion
from portal.modelos import (
    CAMPOS,
    CargaExtracto,
    CONFIRMADO,
    EN_DISPUTA,
    PENDIENTE,
    REVISION_MANUAL,
    CbuPropio,
    Cliente,
    Comprobante,
    Correccion,
    Extraccion,
    MovimientoBanco,
    MovimientoCuenta,
    registrar_movimiento,
)

router = APIRouter(prefix="/admin")
plantillas = Jinja2Templates(directory=Path(__file__).parent / "plantillas")

# Los dos estados que esperan una decisión del dueño.
BANDEJA = (REVISION_MANUAL, EN_DISPUTA)


# ─── El tablero ────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def tablero(request: Request):
    with Sesion() as sesion:
        mes = func.to_char(MovimientoCuenta.fecha, "YYYY-MM")
        por_mes = sesion.execute(
            select(
                mes.label("mes"),
                func.sum(func.greatest(MovimientoCuenta.monto, 0)).label("entro"),
                func.sum(func.least(MovimientoCuenta.monto, 0)).label("salio"),
            ).group_by(mes).order_by(mes.desc()).limit(12)
        ).all()

        por_estado = dict(sesion.execute(
            select(Comprobante.estado, func.count()).group_by(Comprobante.estado)
        ).all())

        clientes = sesion.scalars(
            select(Cliente).order_by(Cliente.saldo.desc())
        ).all()

        # Plata que entró y nadie reclamó. Es el número que dice si falta que
        # alguien suba su comprobante o si el lote no está encontrando.
        sin_comprobante = sesion.execute(
            select(func.count(), func.coalesce(func.sum(MovimientoBanco.importe), 0))
            .where(MovimientoBanco.es_ingreso, MovimientoBanco.comprobante_id.is_(None))
        ).one()

        return plantillas.TemplateResponse(
            request=request,
            name="admin/tablero.html",
            context={
                "por_mes": por_mes,
                "por_estado": por_estado,
                "clientes": clientes,
                "total_saldos": sum(c.saldo for c in clientes),
                "sin_comprobante": sin_comprobante,
                "movimientos_banco": sesion.scalar(
                    select(func.count()).select_from(MovimientoBanco)
                ),
                "en_bandeja": sum(por_estado.get(e, 0) for e in BANDEJA),
            },
        )


# ─── El extracto ───────────────────────────────────────────────────────────

def _contexto_extracto(sesion, **extra) -> dict:
    """Lo que necesita la pantalla del extracto. Se arma igual en los tres caminos."""
    por_cuenta = sesion.execute(
        select(
            MovimientoBanco.cuenta,
            func.count(),
            func.min(MovimientoBanco.fecha),
            func.max(MovimientoBanco.fecha),
        ).group_by(MovimientoBanco.cuenta).order_by(MovimientoBanco.cuenta)
    ).all()
    return {
        "por_cuenta": por_cuenta,
        "cuentas": [c for c, *_ in por_cuenta],
        "total": sum(n for _, n, *_ in por_cuenta),
        "cargas": sesion.scalars(
            select(CargaExtracto).order_by(CargaExtracto.id.desc())
        ).all(),
        **extra,
    }


@router.get("/extracto", response_class=HTMLResponse)
def extracto(request: Request, resumen: str | None = None, error: str | None = None):
    with Sesion() as sesion:
        return plantillas.TemplateResponse(
            request=request, name="admin/extracto.html",
            context=_contexto_extracto(sesion, resumen=resumen, error=error),
        )


@router.post("/extracto")
async def subir_extracto(
    request: Request,
    archivo: UploadFile,
    cuenta: Annotated[str, Form()] = "",
    cuenta_nueva: Annotated[str, Form()] = "",
):
    contenido = await archivo.read()
    # "por hoja" es el valor del selector cuando el archivo trae una cuenta por
    # hoja; cualquier otro valor fuerza TODAS las filas a esa cuenta.
    elegida = (cuenta_nueva.strip() if cuenta == "__nueva__" else cuenta).strip()
    if cuenta == "__nueva__" and not elegida:
        return RedirectResponse(
            "/admin/extracto?error=Elegiste 'otra cuenta' pero no escribiste el nombre.",
            status_code=303,
        )

    with Sesion() as sesion:
        anterior = importar.ya_subido(sesion, contenido)
        try:
            carga = importar.importar(
                contenido,
                cuenta=elegida or None,
                nombre_archivo=archivo.filename or "subido.xlsx",
                sesion=sesion,
            )
            sesion.commit()
        except Exception as falla:  # openpyxl tira de todo si el archivo no es .xlsx
            sesion.rollback()
            return plantillas.TemplateResponse(
                request=request, name="admin/extracto.html",
                context=_contexto_extracto(
                    sesion, error=f"No se pudo leer el archivo: {falla}"),
                status_code=400,
            )

        aviso = (f"«{archivo.filename}» ya lo habías subido el "
                 f"{anterior.importado_en:%d/%m/%Y %H:%M}. " if anterior else "")
        resumen = (f"{aviso}{carga.filas_nuevas} filas nuevas de {carga.filas_leidas} leídas"
                   f" ({carga.filas_duplicadas} ya estaban)")
    return RedirectResponse(f"/admin/extracto?resumen={resumen}", status_code=303)


@router.get("/extracto/carga/{carga_id}/deshacer", response_class=HTMLResponse)
def confirmar_deshacer_carga(request: Request, carga_id: int):
    """Muestra QUÉ se va a perder antes de perderlo. Nunca se borra a ciegas."""
    with Sesion() as sesion:
        carga = sesion.get(CargaExtracto, carga_id)
        if carga is None:
            raise HTTPException(404, "No existe esa carga.")
        acreditadas = sesion.scalars(
            select(MovimientoBanco).where(
                MovimientoBanco.carga_id == carga_id,
                MovimientoBanco.comprobante_id.is_not(None),
            )
        ).all()
        for fila in acreditadas:
            fila.comprobante.cliente.nombre_completo  # se toca antes de cerrar la sesión
        return plantillas.TemplateResponse(
            request=request, name="admin/deshacer_carga.html",
            context={
                "carga": carga,
                "filas": sesion.scalar(
                    select(func.count()).select_from(MovimientoBanco)
                    .where(MovimientoBanco.carga_id == carga_id)
                ),
                "acreditadas": acreditadas,
            },
        )


@router.post("/extracto/carga/{carga_id}/deshacer")
def deshacer_carga(carga_id: int):
    """Borra los movimientos de esa carga y revierte lo que se hubiera acreditado.

    Una fila del banco que ya acreditó plata no se puede borrar sin más: dejaría
    el saldo de un cliente apoyado en un movimiento que ya no existe. Por eso
    cada acreditación se anula con su contra-movimiento y su comprobante vuelve
    al lote, igual que el «deshacer» de la ficha del cliente.
    """
    with Sesion() as sesion:
        carga = sesion.get(CargaExtracto, carga_id)
        if carga is None:
            raise HTTPException(404, "No existe esa carga.")

        for fila in sesion.scalars(
            select(MovimientoBanco).where(
                MovimientoBanco.carga_id == carga_id,
                MovimientoBanco.comprobante_id.is_not(None),
            )
        ):
            comprobante = fila.comprobante
            for movimiento in sesion.scalars(
                select(MovimientoCuenta)
                .where(MovimientoCuenta.comprobante_id == comprobante.id)
            ):
                registrar_movimiento(
                    sesion, comprobante.cliente, date.today(),
                    f"Anulación de: {movimiento.concepto[:70]}", -movimiento.monto,
                )
            comprobante.estado = PENDIENTE
            comprobante.intentos = 0
            comprobante.confianza = None
            comprobante.motivo = (
                f"Se deshizo la carga «{carga.archivo}», que traía su fila del extracto."
            )
            fila.comprobante_id = None

        borradas = sesion.execute(
            delete(MovimientoBanco).where(MovimientoBanco.carga_id == carga_id)
        ).rowcount
        archivo = carga.archivo
        sesion.delete(carga)
        sesion.commit()

    return RedirectResponse(
        f"/admin/extracto?resumen=Se deshizo «{archivo}»: {borradas} movimientos borrados.",
        status_code=303,
    )


@router.get("/exportar")
def exportar_extracto():
    """El extracto entero a Excel, con el comprobante de cada fila y su certeza."""
    with Sesion() as sesion:
        contenido = exportar.a_excel(sesion)
    return Response(
        contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition":
                f'attachment; filename="extracto_conciliado_{date.today():%Y-%m-%d}.xlsx"'
        },
    )


# ─── Todos los comprobantes, con filtros ───────────────────────────────────

@router.get("/comprobantes", response_class=HTMLResponse)
def comprobantes(
    request: Request,
    q: str = "",
    estado: str = "",
    cliente_id: str = "",
):
    """La lista completa. Se filtra por estado, por cliente y por lo que dice adentro.

    El filtro de texto mira **tres cosas a la vez**: el nombre del archivo, el
    motivo, y los campos que leyó la IA (el JSONB completo, como texto). Así
    buscar un CUIT, un monto o un nombre encuentra el comprobante aunque ese dato
    no esté en ninguna columna propia.
    """
    with Sesion() as sesion:
        # La última lectura de cada comprobante, para mostrar qué dice adentro.
        #
        # Se busca por el `id` más alto y NO por el `intento` más alto: correr el
        # lote dos veces deja dos extracciones con `intento = 3` para el mismo
        # comprobante, y entonces el join devolvía DOS filas y el comprobante
        # aparecía duplicado en la lista. El `id` es único y siempre creciente.
        ultima = (
            select(func.max(Extraccion.id).label("id"))
            .group_by(Extraccion.comprobante_id)
            .subquery()
        )
        lectura = (
            select(Extraccion).join(ultima, Extraccion.id == ultima.c.id).subquery()
        )

        consulta = (
            select(Comprobante, Cliente, lectura.c.campos, MovimientoBanco)
            .join(Cliente, Cliente.id == Comprobante.cliente_id)
            .outerjoin(lectura, lectura.c.comprobante_id == Comprobante.id)
            .outerjoin(MovimientoBanco, MovimientoBanco.comprobante_id == Comprobante.id)
        )
        if estado:
            consulta = consulta.where(Comprobante.estado == estado)
        if cliente_id.isdigit():
            consulta = consulta.where(Comprobante.cliente_id == int(cliente_id))
        if q.strip():
            patron = f"%{q.strip()}%"
            consulta = consulta.where(or_(
                Comprobante.archivo.ilike(patron),
                Comprobante.motivo.ilike(patron),
                lectura.c.campos.cast(Text).ilike(patron),
            ))

        filas = sesion.execute(
            consulta.order_by(Comprobante.id.desc())
        ).all()

        return plantillas.TemplateResponse(
            request=request, name="admin/comprobantes.html",
            context={
                "filas": filas,
                "clientes": sesion.scalars(select(Cliente).order_by(Cliente.apellido)).all(),
                "q": q, "estado": estado, "cliente_id": cliente_id,
                "estados": [
                    (PENDIENTE, "Pendientes"), (CONFIRMADO, "Acreditados"),
                    (REVISION_MANUAL, "Para revisar"), (EN_DISPUTA, "En disputa"),
                ],
            },
        )


# ─── El lote ───────────────────────────────────────────────────────────────

@router.get("/lote", response_class=HTMLResponse)
def pantalla_lote(request: Request):
    with Sesion() as sesion:
        pendientes = sesion.scalar(
            select(func.count()).select_from(Comprobante)
            .where(Comprobante.estado == PENDIENTE)
        )
        hay_cbu = sesion.scalar(
            select(func.count()).select_from(CbuPropio)
            .where(CbuPropio.aprobado_en.is_not(None))
        )
    return plantillas.TemplateResponse(
        request=request, name="admin/lote.html",
        context={"pendientes": pendientes, "hay_cbu": hay_cbu, "estado": lote.ESTADO},
    )


@router.post("/lote")
def arrancar_lote(tareas: BackgroundTasks, umbral: Annotated[str, Form()] = "90"):
    # En segundo plano: 20 comprobantes × 3 lecturas son ~30 minutos, y bloquear
    # el navegador media hora no es una opción. `BackgroundTasks` ya viene con
    # FastAPI: no hace falta una cola ni un proceso aparte para un solo dueño.
    if not lote.ESTADO["corriendo"]:
        tareas.add_task(lote.correr, incluir_50=(umbral == "50"))
    return RedirectResponse("/admin/lote", status_code=303)


@router.get("/lote/estado")
def estado_lote() -> dict:
    """Lo consulta la pantalla mientras corre. Devuelve JSON, no HTML."""
    return lote.ESTADO


# ─── La bandeja: lo que decide el dueño ────────────────────────────────────

@router.get("/bandeja", response_class=HTMLResponse)
def bandeja(request: Request):
    with Sesion() as sesion:
        comprobantes = sesion.scalars(
            select(Comprobante).where(Comprobante.estado.in_(BANDEJA))
            .order_by(Comprobante.id)
        ).all()
        # Se toca `cliente` acá adentro para que la plantilla no lo pida ya cerrada.
        for comprobante in comprobantes:
            comprobante.cliente.nombre_completo
        return plantillas.TemplateResponse(
            request=request, name="admin/bandeja.html",
            context={"comprobantes": comprobantes},
        )


@router.get("/bandeja/{comprobante_id}", response_class=HTMLResponse)
def detalle(request: Request, comprobante_id: int, buscar: str = "", error: str | None = None):
    with Sesion() as sesion:
        comprobante = sesion.get(Comprobante, comprobante_id)
        if comprobante is None:
            raise HTTPException(404, "No existe ese comprobante.")
        comprobante.cliente.nombre_completo

        lecturas = lote.ultimas_lecturas(sesion, comprobante_id)
        ultima = lecturas[-1] if lecturas else None
        leido = (ultima.campos if ultima else {}) or {}

        return plantillas.TemplateResponse(
            request=request, name="admin/detalle.html",
            context={
                "comprobante": comprobante,
                "campos": CAMPOS,
                "leido": leido,
                "extracciones": lecturas,
                "diagnostico": lote.diagnostico(sesion, comprobante),
                "filas": _buscar_filas(sesion, buscar or leido.get("monto") or ""),
                "buscar": buscar,
                "error": error,
            },
        )


def _buscar_filas(sesion, texto: str, limite: int = 25):
    """Filas del extracto que puedan ser la del comprobante.

    Busca por monto, por fecha o por texto de la descripción. El monto pasa por
    el mismo parser que el extracto: escribir `4.800,50` tiene que encontrar lo
    mismo que `4800.50`.
    """
    consulta = select(MovimientoBanco).where(MovimientoBanco.es_ingreso)
    texto = (texto or "").strip()
    if texto:
        condiciones = [MovimientoBanco.descripcion.ilike(f"%{texto}%")]
        monto = monto_de_texto(texto)
        if monto is not None:
            condiciones.append(MovimientoBanco.importe == monto)
        try:
            condiciones.append(MovimientoBanco.fecha == date.fromisoformat(texto))
        except ValueError:
            pass
        consulta = consulta.where(or_(*condiciones))
    return sesion.scalars(
        consulta.order_by(MovimientoBanco.fecha.desc()).limit(limite)
    ).all()


@router.post("/bandeja/{comprobante_id}")
async def guardar_detalle(request: Request, comprobante_id: int):
    formulario = await request.form()
    with Sesion() as sesion:
        comprobante = sesion.get(Comprobante, comprobante_id)
        if comprobante is None:
            raise HTTPException(404, "No existe ese comprobante.")

        lecturas = lote.ultimas_lecturas(sesion, comprobante_id)
        ultima = lecturas[-1] if lecturas else None
        leido = (ultima.campos if ultima else {}) or {}

        # Cada campo que el dueño cambia deja su fila: es el ejemplo de
        # entrenamiento que hoy el proyecto no tiene forma de fabricar.
        corregidos = 0
        for campo in CAMPOS:
            correcto = (formulario.get(campo) or "").strip() or None
            anterior = (str(leido.get(campo)) if leido.get(campo) is not None else None)
            if correcto != anterior:
                corregidos += 1
                sesion.add(Correccion(
                    comprobante_id=comprobante_id,
                    campo=campo,
                    valor_leido=anterior,
                    valor_correcto=correcto,
                    descripcion=(formulario.get("descripcion") or "").strip() or None,
                    variante=ultima.variante if ultima else None,
                ))

        elegida = formulario.get("movimiento_id")
        if elegida:
            fila = sesion.get(MovimientoBanco, int(elegida))
            if fila is None:
                raise HTTPException(404, "No existe esa fila del extracto.")
            if fila.comprobante_id not in (None, comprobante_id):
                sesion.rollback()
                return RedirectResponse(
                    f"/admin/bandeja/{comprobante_id}?error="
                    "Esa fila ya es de otro comprobante. Una transferencia es de uno solo.",
                    status_code=303,
                )
            fila.comprobante_id = comprobante_id
            comprobante.estado = CONFIRMADO
            # 100 = lo eligió una persona mirando la imagen. Es más que cualquier
            # escalón de la cascada, y en el Excel se lee distinto a propósito.
            comprobante.confianza = 100
            comprobante.motivo = None
            registrar_movimiento(
                sesion, comprobante.cliente, fila.fecha,
                f"Transferencia acreditada — {fila.descripcion[:80]}",
                fila.importe, comprobante,
            )
        elif formulario.get("accion") == "reintentar":
            comprobante.estado = PENDIENTE
            comprobante.motivo = "El dueño lo mandó de vuelta al lote."
            comprobante.intentos = 0

        sesion.commit()

    destino = "/admin/bandeja" if elegida or formulario.get("accion") == "reintentar" \
        else f"/admin/bandeja/{comprobante_id}"
    return RedirectResponse(destino, status_code=303)


# ─── Clientes ──────────────────────────────────────────────────────────────

@router.get("/clientes", response_class=HTMLResponse)
def clientes(request: Request):
    with Sesion() as sesion:
        return plantillas.TemplateResponse(
            request=request, name="admin/clientes.html",
            context={
                "clientes": sesion.scalars(
                    select(Cliente).order_by(Cliente.saldo.desc())
                ).all()
            },
        )


@router.get("/cliente/{cliente_id}", response_class=HTMLResponse)
def ficha(request: Request, cliente_id: int, error: str | None = None):
    with Sesion() as sesion:
        cliente = sesion.get(Cliente, cliente_id)
        if cliente is None:
            raise HTTPException(404, "No existe ese cliente.")
        return plantillas.TemplateResponse(
            request=request, name="admin/cliente.html",
            context={
                "cliente": cliente,
                "movimientos": sesion.scalars(
                    select(MovimientoCuenta).where(MovimientoCuenta.cliente_id == cliente_id)
                    .order_by(MovimientoCuenta.fecha.desc(), MovimientoCuenta.id.desc())
                ).all(),
                "error": error,
            },
        )


@router.post("/cliente/{cliente_id}/movimiento")
def cargar_movimiento(
    cliente_id: int,
    concepto: Annotated[str, Form()],
    monto: Annotated[str, Form()],
    signo: Annotated[str, Form()] = "-",
    fecha: Annotated[str, Form()] = "",
):
    valor = monto_de_texto(monto)
    if valor is None or valor <= 0:
        return RedirectResponse(
            f"/admin/cliente/{cliente_id}?error="
            "El monto no se entendió. Escribilo como 12.500,00 o 12500.00, sin signo.",
            status_code=303,
        )
    with Sesion() as sesion:
        cliente = sesion.get(Cliente, cliente_id)
        if cliente is None:
            raise HTTPException(404, "No existe ese cliente.")
        registrar_movimiento(
            sesion, cliente,
            date.fromisoformat(fecha) if fecha else date.today(),
            concepto.strip() or "Ajuste del administrador",
            valor if signo == "+" else -valor,
        )
        sesion.commit()
    return RedirectResponse(f"/admin/cliente/{cliente_id}", status_code=303)


@router.post("/movimiento/{movimiento_id}/deshacer")
def deshacer(movimiento_id: int):
    """Deshacer no borra: agrega el movimiento inverso y libera la fila del extracto.

    Borrar la línea dejaría el saldo bien y la historia mal. Con el contra-movimiento
    el libro conserva las dos y se puede reconstruir qué pasó y cuándo.
    """
    with Sesion() as sesion:
        original = sesion.get(MovimientoCuenta, movimiento_id)
        if original is None:
            raise HTTPException(404, "No existe ese movimiento.")
        cliente_id = original.cliente_id

        registrar_movimiento(
            sesion, original.cliente, date.today(),
            f"Anulación de: {original.concepto[:70]}", -original.monto,
        )

        if original.comprobante_id:
            fila = sesion.scalars(
                select(MovimientoBanco)
                .where(MovimientoBanco.comprobante_id == original.comprobante_id)
            ).first()
            if fila:
                fila.comprobante_id = None
            comprobante = sesion.get(Comprobante, original.comprobante_id)
            if comprobante:
                comprobante.estado = PENDIENTE
                comprobante.intentos = 0
                comprobante.motivo = "Se anuló la acreditación: vuelve al lote."
        sesion.commit()
    return RedirectResponse(f"/admin/cliente/{cliente_id}", status_code=303)


# ─── CBU propios ───────────────────────────────────────────────────────────

@router.get("/cbu", response_class=HTMLResponse)
def cbu(request: Request, error: str | None = None):
    with Sesion() as sesion:
        return plantillas.TemplateResponse(
            request=request, name="admin/cbu.html",
            context={
                "cbus": sesion.scalars(select(CbuPropio).order_by(CbuPropio.id)).all(),
                "error": error,
            },
        )


@router.post("/cbu")
def agregar_cbu(
    valor: Annotated[str, Form()], etiqueta: Annotated[str, Form()] = ""
):
    digitos = solo_digitos(valor)
    # 22 dígitos un CBU/CVU, 11 un CUIT. Cualquier otra cosa es un error de tipeo,
    # y un CBU propio equivocado hace que ningún comprobante verifique nunca.
    if digitos is None or len(digitos) not in (11, 22):
        return RedirectResponse(
            "/admin/cbu?error=Un CBU/CVU tiene 22 dígitos y un CUIT 11. "
            f"Eso tiene {len(digitos or '')}.",
            status_code=303,
        )
    with Sesion() as sesion:
        if sesion.scalar(select(CbuPropio).where(CbuPropio.valor == digitos)):
            return RedirectResponse("/admin/cbu?error=Ese ya está cargado.", status_code=303)
        sesion.add(CbuPropio(
            valor=digitos, etiqueta=etiqueta.strip() or None,
            origen="manual", aprobado_en=datetime.now(),
        ))
        sesion.commit()
    return RedirectResponse("/admin/cbu", status_code=303)


@router.post("/cbu/{cbu_id}/borrar")
def borrar_cbu(cbu_id: int):
    with Sesion() as sesion:
        fila = sesion.get(CbuPropio, cbu_id)
        if fila:
            sesion.delete(fila)
            sesion.commit()
    return RedirectResponse("/admin/cbu", status_code=303)

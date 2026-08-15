"""El portal del cliente: ve su saldo, su actividad y sube comprobantes.

    ia/.venv/bin/uvicorn portal.app:app --reload --port 8000

Sin contraseña a propósito (decisión del usuario): el id del cliente va en la
URL y no hay sesión. El día que esto salga de la máquina, hace falta login.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from portal import archivos
from portal.db import Sesion
from portal.modelos import PENDIENTE, Cliente, Comprobante, MovimientoCuenta

AQUI = Path(__file__).parent

app = FastAPI(title="Portal del cliente")
app.mount("/estaticos", StaticFiles(directory=AQUI / "estaticos"), name="estaticos")
plantillas = Jinja2Templates(directory=AQUI / "plantillas")


def pesos(monto: Decimal) -> str:
    """1234567.8 → '1.234.567,80'. Formato argentino, sin símbolo."""
    return f"{monto:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def dia(momento: date | datetime | None) -> str:
    return momento.strftime("%d/%m/%Y") if momento else "—"


plantillas.env.filters["pesos"] = pesos
plantillas.env.filters["dia"] = dia

# El panel del dueño vive en su propio módulo. Se importa DESPUÉS de definir los
# filtros porque comparte el entorno de Jinja a través de la carpeta de plantillas.
from portal.admin import plantillas as plantillas_admin, router as router_admin  # noqa: E402

plantillas_admin.env.filters["pesos"] = pesos
plantillas_admin.env.filters["dia"] = dia
app.include_router(router_admin)


@app.get("/", response_class=HTMLResponse)
def elegir(request: Request):
    with Sesion() as sesion:
        clientes = sesion.scalars(select(Cliente).order_by(Cliente.apellido)).all()
        return plantillas.TemplateResponse(
            request=request, name="elegir.html", context={"clientes": clientes}
        )


@app.get("/cliente/{cliente_id}", response_class=HTMLResponse)
def cuenta(request: Request, cliente_id: int):
    with Sesion() as sesion:
        cliente = _buscar_cliente(sesion, cliente_id)
        movimientos = sesion.scalars(
            select(MovimientoCuenta)
            .where(MovimientoCuenta.cliente_id == cliente_id)
            .order_by(MovimientoCuenta.fecha.desc(), MovimientoCuenta.id.desc())
        ).all()
        comprobantes = sesion.scalars(
            select(Comprobante)
            .where(Comprobante.cliente_id == cliente_id)
            .order_by(Comprobante.id.desc())
        ).all()
        return plantillas.TemplateResponse(
            request=request,
            name="cuenta.html",
            context={
                "cliente": cliente,
                "movimientos": movimientos,
                "comprobantes": comprobantes,
            },
        )


@app.get("/cliente/{cliente_id}/subir", response_class=HTMLResponse)
def formulario(request: Request, cliente_id: int):
    with Sesion() as sesion:
        cliente = _buscar_cliente(sesion, cliente_id)
        return plantillas.TemplateResponse(
            request=request, name="subir.html", context={"cliente": cliente}
        )


@app.post("/cliente/{cliente_id}/subir")
async def recibir(
    request: Request,
    cliente_id: int,
    archivo: UploadFile,
    fecha_declarada: Annotated[str, Form()] = "",
):
    contenido = await archivo.read()
    with Sesion() as sesion:
        cliente = _buscar_cliente(sesion, cliente_id)
        try:
            # El archivo primero y la fila después: al revés queda una fila
            # apuntando a un archivo que no existe.
            ruta = archivos.guardar(cliente_id, archivo.filename or "", contenido)
            fecha = date.fromisoformat(fecha_declarada) if fecha_declarada else None
        except archivos.ArchivoRechazado as rechazo:
            return _volver_al_formulario(request, cliente, str(rechazo))
        except ValueError:
            return _volver_al_formulario(request, cliente, "La fecha no se entendió.")

        sesion.add(
            Comprobante(
                cliente_id=cliente_id,
                archivo=ruta,
                fecha_declarada=fecha,
                estado=PENDIENTE,
            )
        )
        sesion.commit()

    return RedirectResponse(f"/cliente/{cliente_id}", status_code=303)


@app.get("/cliente/{cliente_id}/comprobante/{comprobante_id}")
def imagen(cliente_id: int, comprobante_id: int):
    with Sesion() as sesion:
        comprobante = sesion.get(Comprobante, comprobante_id)
        # El id del cliente no es decorativo: sin este cotejo, cualquiera ve el
        # comprobante de cualquiera cambiando un número en la URL.
        if comprobante is None or comprobante.cliente_id != cliente_id:
            raise HTTPException(404, "No existe ese comprobante.")
        ruta = (archivos.CARPETA / comprobante.archivo).resolve()

    if not ruta.is_relative_to(archivos.CARPETA.resolve()) or not ruta.exists():
        raise HTTPException(404, "El archivo no está.")
    return FileResponse(ruta)


def _buscar_cliente(sesion, cliente_id: int) -> Cliente:
    cliente = sesion.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(404, "No existe ese cliente.")
    return cliente


def _volver_al_formulario(request: Request, cliente: Cliente, error: str) -> HTMLResponse:
    return plantillas.TemplateResponse(
        request=request,
        name="subir.html",
        context={"cliente": cliente, "error": error},
        status_code=400,
    )

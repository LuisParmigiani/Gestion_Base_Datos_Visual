"""
Generador del dataset sintético de entrenamiento (F8).

Copia de `viejo/generar_sinteticos.py` — que es de solo lectura y no se toca —
con los cambios que la sesión 3 dejó diagnosticados:

  1. OUT_DIR anclado al archivo, no al cwd. El original escribió una vez dentro
     de viejo/comprobantes/ por correrse desde el directorio equivocado.
  2. coelsa_id de 22 caracteres. El original generaba 16 o 20: ninguno del largo
     real, así que el modelo aprendía un formato que no existe.
  3. La ETIQUETA sale canónica (monto 275054.91, CUIT sin guiones) mientras la
     IMAGEN sigue mostrando el formato argentino ($ 275.054,91). Traducir de uno
     al otro es exactamente lo que el fine-tuning tiene que enseñar.
  4. El volcado a JSONL vive acá, en el formato images/messages que el trainer
     de mlx-vlm 0.1.15 realmente lee (viejo/gestionar_dataset.py escribía
     image/prompt/answer: ninguna de esas tres claves existe para el trainer, y
     es el bug que mató el intento anterior).

Bancos soportados (transferencia_saliente):
  Mercado Pago, Banco Macro, Santander, Galicia, BBVA Francés,
  Banco Nación, Naranja X, Brubank, Ualá, Personal Pay.

    python ia/generar.py --n 4
"""

import argparse
import json
import random
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from faker import Faker

fake = Faker("es_AR")

AQUI = Path(__file__).resolve().parent
SALIDA_DIR = AQUI / "sinteticos"
OUT_DIR = SALIDA_DIR / "imagenes"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# FUENTES — paths reales en macOS
# ---------------------------------------------------------------------------
FUENTES = {
    "arial":      "/System/Library/Fonts/Supplemental/Arial.ttf",
    "arial_bold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "helvetica":  "/System/Library/Fonts/Helvetica.ttc",
    "hel_neue":   "/System/Library/Fonts/HelveticaNeue.ttc",
    "avenir":     "/System/Library/Fonts/Avenir Next.ttc",
}


def fnt(familia: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FUENTES[familia], size)


# ---------------------------------------------------------------------------
# HELPERS DE DATOS ARGENTINOS
# ---------------------------------------------------------------------------
MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_ES = ["lunes", "martes", "miércoles", "jueves",
           "viernes", "sábado", "domingo"]

_PREFIJO_SALUDO = re.compile(
    r"^(sr\(?a?\)?\.?|sra\.?|dr\(?a?\)?\.?|dra\.?|don|doña|ing\.?|lic\.?)\s+",
    re.IGNORECASE,
)


def gen_cuit_ar(con_guiones: bool = True) -> str:
    prefijo = random.choice([20, 23, 24, 27])
    cuerpo = random.randint(10_000_000, 99_999_999)
    verif = random.randint(0, 9)
    return f"{prefijo}-{cuerpo}-{verif}" if con_guiones else f"{prefijo}{cuerpo}{verif}"


CBU_PREFIJOS = {
    "Mercado Pago":     "0000003100",
    "Banco Macro":      "2850590",
    "Banco Santander":  "0720370",
    "Banco Galicia":    "0070172",
    "BBVA Francés":     "0170148",
    "Banco Nación":     "0110599",
    "Naranja X":        "4530000",
    "Brubank":          "1430001",
    "Ualá":             "0000076",
    "Personal Pay":     "0000172",
}


def gen_cbu(banco: str) -> str:
    pref = CBU_PREFIJOS.get(banco, "0000000")
    resto = "".join(str(random.randint(0, 9)) for _ in range(22 - len(pref)))
    return pref + resto


# Sin I ni O: se confunden con 1 y 0 y el modelo no tiene por qué aprender esa
# ambigüedad. Los 84 COELSA del extracto real miden 22, igual que este.
_ALFABETO_COELSA = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def gen_coelsa() -> str:
    return "".join(random.choice(_ALFABETO_COELSA) for _ in range(22))


def gen_alias() -> str:
    palabras = [w.lower() for w in fake.words(nb=3)]
    return ".".join(palabras)[:25]


def fmt_monto_ar(monto: float, con_decimales: bool = True) -> str:
    s = f"{monto:,.2f}" if con_decimales else f"{monto:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_fecha_corta(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y")


def fmt_fecha_larga_ar(dt: datetime) -> str:
    dia = DIAS_ES[dt.weekday()]
    mes = MESES_ES[dt.month - 1]
    return f"{dia.capitalize()}, {dt.day} de {mes} de {dt.year} a las {dt.strftime('%H:%M')} hs"


def gen_fecha_hora_reciente() -> datetime:
    base = datetime.now() - timedelta(days=random.randint(0, 60))
    return base.replace(
        hour=random.randint(6, 23),
        minute=random.randint(0, 59),
        second=0,
        microsecond=0,
    )


def nombre_persona() -> str:
    nombre = fake.name()
    while True:
        nuevo = _PREFIJO_SALUDO.sub("", nombre).strip()
        if nuevo == nombre:
            break
        nombre = nuevo
    return nombre.title()


def banco_destino_random(excluir: Optional[str] = None) -> str:
    candidatos = [b for b in CBU_PREFIJOS if b != excluir]
    return random.choice(candidatos)


# ---------------------------------------------------------------------------
# RUIDO WHATSAPP REALISTA
# ---------------------------------------------------------------------------
def ruido_whatsapp(img: Image.Image) -> Image.Image:
    # 80% derechos, 20% rotación leve — los screenshots móviles reales casi nunca
    # están torcidos; reservamos la inclinación para robustez ocasional.
    if random.random() < 0.20:
        angulo = random.uniform(-2.0, 2.0)
        img = img.rotate(angulo, resample=Image.BICUBIC, expand=True, fillcolor=(245, 245, 245))

    if random.random() < 0.55:
        target_w = random.choice([720, 600, 540])
        ratio = target_w / img.width
        img = img.resize((target_w, int(img.height * ratio)), Image.LANCZOS)

    if random.random() < 0.10:
        img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.2, 0.4)))

    return img


def guardar_con_compresion(img: Image.Image, ruta: Path) -> None:
    quality = random.randint(65, 88)
    img.convert("RGB").save(ruta, "JPEG", quality=quality, optimize=True)


# ===========================================================================
#                              LOGOS POR BANCO
# ===========================================================================
def logo_mp(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    r = 28
    d.ellipse([x, y, x + 2*r, y + 2*r], fill="#00B1EA")
    d.arc([x + 6, y + 16, x + 2*r - 14, y + 2*r - 6], 200, 340, fill="white", width=5)
    d.arc([x + 14, y + 16, x + 2*r - 6, y + 2*r - 6], 200, 340, fill="white", width=5)
    d.text((x + 2*r + 10, y + 2), "mercado", fill="#00B1EA", font=fnt("arial_bold", 24))
    d.text((x + 2*r + 10, y + 28), "pago", fill="#1A1A1A", font=fnt("arial_bold", 24))


def logo_macro(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # Curvas concéntricas azul + texto "Macro"
    color = "#1B2A6B"
    for i, r in enumerate([10, 22, 34]):
        d.arc([x - r, y + 18 - r//2, x + r, y + 18 + r + r//2],
              start=180, end=360, fill=color, width=4)
    d.text((x + 50, y + 4), "Macro", fill=color, font=fnt("arial_bold", 42))


def logo_santander(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # "Llama" estilizada roja: arco grueso semicirc + bezier-like con líneas
    rojo = "#EC0000"
    d.arc([x, y + 6, x + 44, y + 46], start=20, end=340, fill=rojo, width=8)
    d.line([(x + 22, y + 0), (x + 44, y + 22)], fill=rojo, width=8)
    d.text((x + 60, y + 6), "Santander", fill=rojo, font=fnt("arial_bold", 36))


def logo_galicia(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # "Galicia" en naranja con cuadrito decorativo
    naranja = "#F47920"
    d.rectangle([x, y + 8, x + 30, y + 38], fill=naranja)
    d.text((x + 8, y + 10), "G", fill="white", font=fnt("arial_bold", 26))
    d.text((x + 42, y + 6), "Galicia", fill="#2A2A2A", font=fnt("arial_bold", 36))


def logo_bbva(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    azul = "#072146"
    d.text((x, y), "BBVA", fill=azul, font=fnt("arial_bold", 48))
    d.line([(x, y + 56), (x + 130, y + 56)], fill=azul, width=3)


def logo_nacion(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # "BNA+" celeste con + naranja
    celeste = "#3FA9F5"
    naranja = "#F58220"
    d.text((x, y), "BNA", fill=celeste, font=fnt("arial_bold", 54))
    d.text((x + 110, y - 4), "+", fill=naranja, font=fnt("arial_bold", 58))


def logo_naranjax(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    naranja = "#F25A22"
    d.text((x, y), "Naranja", fill=naranja, font=fnt("arial_bold", 36))
    d.text((x + 140, y), "X", fill="#1A1A1A", font=fnt("arial_bold", 38))


def logo_brubank(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # Texto blanco sobre fondo violeta (asume que ya hay un fondo violeta detrás).
    d.text((x, y), "brubank", fill="white", font=fnt("arial_bold", 38))
    # Estrellita
    cx, cy = x + 175, y + 12
    for ang in range(0, 360, 72):
        from math import cos, sin, radians
        d.line([(cx, cy), (cx + 8*cos(radians(ang)), cy + 8*sin(radians(ang)))],
               fill="white", width=2)


def logo_uala(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # "ualá" minimal celeste
    celeste = "#22B8E5"
    d.text((x, y), "ualá", fill=celeste, font=fnt("arial_bold", 46))


def logo_personalpay(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    violeta = "#7B2D9F"
    d.text((x, y), "personal", fill=violeta, font=fnt("arial_bold", 30))
    d.text((x + 130, y), "pay", fill="#1A1A1A", font=fnt("arial_bold", 30))


# ===========================================================================
# HELPER LAYOUT KEY-VALUE (Santander, BBVA, Macro web, Nación)
# ===========================================================================
def fila_kv_izq_der(d, y, w, label, valor, *,
                    color_label="#6E6E6E", color_valor="#1A1A1A",
                    f_label=None, f_valor=None,
                    margen=50, con_linea=True):
    f_label = f_label or fnt("arial", 22)
    f_valor = f_valor or fnt("arial_bold", 22)
    d.text((margen, y), label, fill=color_label, font=f_label)
    ancho_v = d.textlength(valor, font=f_valor)
    d.text((w - margen - ancho_v, y), valor, fill=color_valor, font=f_valor)
    if con_linea:
        d.line([(margen, y + 42), (w - margen, y + 42)], fill="#EEEEEE", width=1)


# ===========================================================================
#                              TEMPLATES POR BANCO
# ===========================================================================
def _datos_comunes(banco_emisor: str) -> dict:
    """Genera el set de datos que comparten todos los templates."""
    dt = gen_fecha_hora_reciente()
    monto = round(random.uniform(500, 350_000), 2)
    nombre_emi = nombre_persona()
    nombre_rec = nombre_persona()
    cuit_emi = gen_cuit_ar()
    cuit_rec = gen_cuit_ar()
    cbu_emi = gen_cbu(banco_emisor)
    banco_rec = banco_destino_random(excluir=banco_emisor)
    cbu_rec = gen_cbu(banco_rec)
    return {
        "dt": dt, "monto": monto,
        "nombre_emi": nombre_emi, "nombre_rec": nombre_rec,
        "cuit_emi": cuit_emi, "cuit_rec": cuit_rec,
        "cbu_emi": cbu_emi, "cbu_rec": cbu_rec,
        "banco_rec": banco_rec,
    }


def solo_digitos(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def _gt(banco_emisor: str, datos: dict, *,
        referencia: str, coelsa_id: Optional[str] = None,
        moneda: str = "ARS", concepto: str = "Varios",
        con_decimales: bool = True, ocultos: Sequence[str] = ()) -> dict:
    """La etiqueta, en formato CANÓNICO — no en el que muestra la imagen.

    La imagen dice `$ 275.054,91` y `20-53594652-7`; la etiqueta dice
    `275054.91` y `20535946527`. Esa traducción es lo que el fine-tuning tiene
    que aprender, y es la que `web/src/lib/motor.ts` necesita para conciliar.

    `con_decimales` tiene que valer lo mismo que usó el template al DIBUJAR el
    monto: si la imagen muestra `$ 198.005` sin centavos, la etiqueta dice
    `198005.00`. Etiquetar `198004.87` sería enseñarle a inventar centavos que
    no están en la imagen.

    `ocultos` son los campos que ESTE template no dibuja. Van a null, y esa es
    la regla de la que depende todo: **la etiqueta describe la imagen, no los
    datos con que se generó.** Un comprobante del Santander no muestra el CUIT
    del emisor; etiquetarlo igual le enseña al modelo a inventar un CUIT de 11
    dígitos que pasa cualquier validación de formato. Es el peor error posible
    en este proyecto, porque acusa a un cliente honesto con un dato que parece
    perfectamente válido.

    Mismo criterio que `coelsa_id` y `con_decimales`, que ya lo aplicaban:
    la diferencia es que ahora vale para los 16 campos y no para dos.
    """
    monto = round(datos["monto"], 2 if con_decimales else 0)
    etiqueta = {
        # El vocabulario lo fija la VERDAD, no el generador: la columna
        # `comprobante.tipo_operacion` dice "Transferencia" en 50 de 55 revisados. Hasta
        # 2026-08-10 acá decía "transferencia_saliente" y el dataset se contradecía consigo
        # mismo — 300 sintéticas con una etiqueta y 32 reales con la otra. `lora_v3` aprendió
        # la mayoritaria y contestó "transferencia_saliente" en los 16 apartados: acertó los
        # 16 y la medición le contó CERO. Son 6,3 puntos de los 256 campos.
        # OJO: las claves `(banco, "transferencia_saliente")` de la tabla de plantillas son
        # otra cosa — enrutan qué función dibuja el comprobante y NO salen en la etiqueta.
        "tipo_operacion": "Transferencia",
        "monto": f"{monto:.2f}",
        "moneda": moneda,
        "fecha": datos["dt"].strftime("%Y-%m-%d"),
        "hora": datos["dt"].strftime("%H:%M"),
        "nombre_emisor": datos["nombre_emi"],
        "cuit_emisor": solo_digitos(datos["cuit_emi"]),
        "cbu_cvu_emisor": datos["cbu_emi"],
        "banco_emisor": banco_emisor,
        "nombre_receptor": datos["nombre_rec"],
        "cuit_receptor": solo_digitos(datos["cuit_rec"]),
        "cbu_cvu_receptor": datos["cbu_rec"],
        "banco_receptor": datos["banco_rec"],
        "concepto": concepto,
        "referencia": referencia,
        "coelsa_id": coelsa_id,
    }
    desconocidos = set(ocultos) - set(etiqueta)
    assert not desconocidos, f"campo inexistente en `ocultos`: {desconocidos}"
    return {k: (None if k in ocultos else v) for k, v in etiqueta.items()}


# ---------------------------------------------------------------------------
# MERCADO PAGO
# ---------------------------------------------------------------------------
def comp_mp_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"mp_saliente_{uid}.jpg"
    dat = _datos_comunes("Mercado Pago")
    referencia = str(random.randint(10**11, 10**12 - 1))
    cod_id = gen_coelsa()

    W, H = 820, 1340
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    if random.random() < 0.55:
        wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(wm).text((-30, H//2 - 200), "ACREDITADA",
                                fill=(220, 232, 245, 120), font=fnt("arial_bold", 150))
        wm = wm.rotate(-22, resample=Image.BICUBIC)
        img.paste(wm, (0, 0), wm)

    logo_mp(d, 55, 65)
    d.text((55, 175), "Comprobante de transferencia",
           fill="#1A1A1A", font=fnt("arial_bold", 38))
    d.text((55, 230), fmt_fecha_larga_ar(dat["dt"]),
           fill="#7A7A7A", font=fnt("arial", 22))
    d.line([(55, 280), (W - 55, 280)], fill="#E5E5E5", width=1)

    d.text((55, 320), f"$ {fmt_monto_ar(dat['monto'], False)}",
           fill="#1A1A1A", font=fnt("arial_bold", 64))
    d.text((55, 410), "Motivo: Varios", fill="#7A7A7A", font=fnt("arial", 22))

    y_de = 495
    d.ellipse([48, y_de, 64, y_de + 16], fill="#00B1EA")
    d.line([(56, y_de + 16), (56, y_de + 220)], fill="#00B1EA", width=2)
    d.text((90, y_de - 6), "De", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((90, y_de + 24), dat["nombre_emi"], fill="#1A1A1A", font=fnt("arial_bold", 26))
    d.text((90, y_de + 62), f"CUIT/CUIL: {dat['cuit_emi']}", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((90, y_de + 94), "Mercado Pago", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((90, y_de + 126), f"CVU: {dat['cbu_emi']}", fill="#7A7A7A", font=fnt("arial", 22))

    y_pa = y_de + 230
    d.ellipse([48, y_pa, 64, y_pa + 16], fill="#00B1EA")
    d.text((90, y_pa - 6), "Para", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((90, y_pa + 24), dat["nombre_rec"], fill="#1A1A1A", font=fnt("arial_bold", 26))
    d.text((90, y_pa + 62), f"CUIT/CUIL: {dat['cuit_rec']}", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((90, y_pa + 94), dat["banco_rec"], fill="#7A7A7A", font=fnt("arial", 22))
    d.text((90, y_pa + 126), f"CVU: {dat['cbu_rec']}", fill="#7A7A7A", font=fnt("arial", 22))

    y_ref = y_pa + 210
    d.line([(55, y_ref), (W - 55, y_ref)], fill="#E5E5E5", width=1)
    d.text((55, y_ref + 30), "Número de operación de Mercado Pago",
           fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, y_ref + 62), referencia, fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((55, y_ref + 110), "Código de identificación",
           fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, y_ref + 142), cod_id, fill="#1A1A1A", font=fnt("arial_bold", 24))

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Mercado Pago", dat,
                          referencia=referencia, coelsa_id=cod_id,
                          con_decimales=False,
                          ocultos=["hora"])


# ---------------------------------------------------------------------------
# BANCO MACRO
# ---------------------------------------------------------------------------
def comp_macro_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"macro_saliente_{uid}.jpg"
    dat = _datos_comunes("Banco Macro")
    referencia = str(random.randint(10**7, 10**8 - 1))
    coelsa = gen_coelsa()

    W, H = 820, 1500
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # Header lavanda
    d.rectangle([0, 0, W, 320], fill="#E8E8F5")
    logo_macro(d, W//2 - 60, 50)
    d.text((90, 160), "Comprobante de", fill="#1A1A1A", font=fnt("arial_bold", 44))
    d.text((90, 215), "transferencia", fill="#1A1A1A", font=fnt("arial_bold", 44))

    # Datos de transferencia
    d.text((50, 370), "Datos de transferencia",
           fill="#1B2A6B", font=fnt("arial_bold", 28))

    y = 430
    d.text((50, y), "Para", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((50, y + 36), dat["nombre_rec"], fill="#1A1A1A", font=fnt("arial", 24))
    d.text((50, y + 80), "Cuenta:", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((50, y + 116), f"{dat['banco_rec']} - CA ARS {random.randint(1000, 9999)}",
           fill="#1A1A1A", font=fnt("arial", 24))
    d.text((50, y + 160), "CUIL/CUIT:", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((50, y + 196), dat["cuit_rec"].replace("-", ""),
           fill="#1A1A1A", font=fnt("arial", 24))

    d.line([(50, y + 260), (W - 50, y + 260)], fill="#EFEFEF", width=1)

    y2 = y + 290
    d.text((50, y2), "Desde", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((50, y2 + 36), dat["nombre_emi"], fill="#1A1A1A", font=fnt("arial", 24))
    d.text((50, y2 + 80), "Cuenta:", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((50, y2 + 116), f"Banco Macro - CA $ {random.randint(1000, 9999)}",
           fill="#1A1A1A", font=fnt("arial", 24))
    d.text((50, y2 + 160), "CUIL/CUIT:", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((50, y2 + 196), dat["cuit_emi"].replace("-", ""),
           fill="#1A1A1A", font=fnt("arial", 24))

    d.line([(50, y2 + 260), (W - 50, y2 + 260)], fill="#EFEFEF", width=1)

    y3 = y2 + 290
    for i, (k, v) in enumerate([
        ("Monto:", f"$ {fmt_monto_ar(dat['monto'], False)}"),
        ("Concepto:", "Varios"),
        ("N° de operación:", referencia),
        ("Fecha y hora:", f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} h"),
        ("ID COELSA:", coelsa),
    ]):
        d.text((50, y3 + i*86), k, fill="#1A1A1A", font=fnt("arial_bold", 22))
        d.text((50, y3 + i*86 + 32), v, fill="#1A1A1A", font=fnt("arial", 22))

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Banco Macro", dat,
                          referencia=referencia, coelsa_id=coelsa,
                          con_decimales=False,
                          ocultos=["cbu_cvu_emisor", "cbu_cvu_receptor"])


# ---------------------------------------------------------------------------
# SANTANDER
# ---------------------------------------------------------------------------
def comp_santander_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"santander_saliente_{uid}.jpg"
    dat = _datos_comunes("Banco Santander")
    referencia = str(random.randint(10**7, 10**8 - 1))

    W, H = 820, 1500
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    logo_santander(d, W//2 - 130, 50)
    d.text((50, 170), "Comprobante de Transferencia",
           fill="#1A1A1A", font=fnt("arial_bold", 36))
    d.line([(50, 240), (W - 50, 240)], fill="#E5E5E5", width=1)

    filas = [
        ("Importe debitado", f"$ {fmt_monto_ar(dat['monto'])}"),
        ("Cuenta destino", dat["cbu_rec"]),
        ("Titular cuenta destino", dat["nombre_rec"]),
        ("Cuenta débito", f"CTA $ {random.randint(100, 999)}-{random.randint(100000, 999999)}/{random.randint(0, 9)}"),
        ("Concepto transferencia", "Varios"),
        ("Información adicional", "Varios"),
        ("Plazo de acreditación", "Inmediato"),
        ("Fecha de ejecución", fmt_fecha_corta(dat["dt"])),
        ("N° comprobante", referencia),
    ]
    y = 290
    for lbl, val in filas:
        fila_kv_izq_der(d, y, W, lbl, val)
        y += 90

    # Disclaimer al pie
    d.text((50, y + 60),
           "Recuerde que puede consultar e imprimir este comprobante ingresando al",
           fill="#7A7A7A", font=fnt("arial", 18))
    d.text((50, y + 86),
           "módulo de Pagos y Transferencias en Online Banking Personas.",
           fill="#7A7A7A", font=fnt("arial", 18))

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Banco Santander", dat, referencia=referencia,
                          ocultos=["hora", "nombre_emisor", "cuit_emisor", "cbu_cvu_emisor", "cuit_receptor", "banco_receptor"])


# ---------------------------------------------------------------------------
# GALICIA
# ---------------------------------------------------------------------------
def comp_galicia_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"galicia_saliente_{uid}.jpg"
    dat = _datos_comunes("Banco Galicia")
    referencia = str(random.randint(10**5, 10**6 - 1))

    W, H = 820, 1340
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    logo_galicia(d, 55, 55)
    d.text((55, 130), "Comprobante de transferencia",
           fill="#2A2A2A", font=fnt("arial_bold", 32))
    d.line([(55, 195), (W - 55, 195)], fill="#E5E5E5", width=1)

    d.text((55, 225), "Importe", fill="#7A7A7A", font=fnt("arial", 24))
    d.text((55, 265), f"$ {fmt_monto_ar(dat['monto'])}",
           fill="#2A2A2A", font=fnt("arial_bold", 38))
    d.line([(55, 340), (W - 55, 340)], fill="#EFEFEF", width=1)

    d.text((55, 370), "Destino", fill="#7A7A7A", font=fnt("arial", 24))
    d.text((55, 410), dat["nombre_rec"], fill="#2A2A2A", font=fnt("arial_bold", 28))
    d.text((55, 455), f"CBU/CVU: {dat['cbu_rec']}", fill="#2A2A2A", font=fnt("arial", 22))
    d.text((55, 495), f"CUIT/CUIL: {dat['cuit_rec']}", fill="#7A7A7A", font=fnt("arial", 22))
    d.line([(55, 560), (W - 55, 560)], fill="#EFEFEF", width=1)

    d.text((55, 590), "Origen", fill="#7A7A7A", font=fnt("arial", 24))
    d.text((55, 630), dat["nombre_emi"], fill="#2A2A2A", font=fnt("arial_bold", 28))
    d.text((55, 675), "Cuenta Corriente / Caja de Ahorros",
           fill="#2A2A2A", font=fnt("arial", 22))
    d.line([(55, 740), (W - 55, 740)], fill="#EFEFEF", width=1)

    d.text((55, 770), "Número de transacción", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 810), referencia, fill="#2A2A2A", font=fnt("arial_bold", 26))

    d.text((55, 870), "Fecha", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 910), f"{fmt_fecha_corta(dat['dt'])} a las {dat['dt'].strftime('%H:%M')} hs",
           fill="#2A2A2A", font=fnt("arial", 24))

    d.text((55, 970), "Canal", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 1010), "App Galicia", fill="#2A2A2A", font=fnt("arial", 24))

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Banco Galicia", dat, referencia=referencia,
                          ocultos=["cuit_emisor", "cbu_cvu_emisor", "banco_receptor", "concepto"])


# ---------------------------------------------------------------------------
# BBVA FRANCÉS
# ---------------------------------------------------------------------------
def comp_bbva_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"bbva_saliente_{uid}.jpg"
    dat = _datos_comunes("BBVA Francés")
    referencia = str(random.randint(10**7, 10**8 - 1))

    W, H = 820, 1380
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    logo_bbva(d, 55, 55)
    d.text((55, 135), "Comprobante de transferencia",
           fill="#072146", font=fnt("arial_bold", 30))
    d.line([(55, 195), (W - 55, 195)], fill="#072146", width=2)

    # Card monto
    d.rectangle([55, 230, W - 55, 360], fill="#F4F6F9")
    d.text((80, 255), "Monto de la operación", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((80, 300), f"$ {fmt_monto_ar(dat['monto'])} ARS",
           fill="#072146", font=fnt("arial_bold", 32))

    d.text((55, 395), "Cuenta de origen", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 430), dat["nombre_emi"], fill="#2A2A2A", font=fnt("arial_bold", 24))
    d.text((55, 470), "Caja de ahorros en pesos", fill="#7A7A7A", font=fnt("arial", 22))
    d.line([(55, 525), (W - 55, 525)], fill="#EEEEEE", width=1)

    d.text((55, 555), "Cuenta de destino", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 590), dat["nombre_rec"], fill="#2A2A2A", font=fnt("arial_bold", 24))
    d.text((55, 630), f"CBU: {dat['cbu_rec']}", fill="#2A2A2A", font=fnt("arial", 22))
    d.text((55, 670), f"CUIT/CUIL: {dat['cuit_rec']}", fill="#7A7A7A", font=fnt("arial", 22))
    d.line([(55, 725), (W - 55, 725)], fill="#EEEEEE", width=1)

    d.text((55, 755), "Fecha y hora de ejecución", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 790), f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} hs",
           fill="#2A2A2A", font=fnt("arial", 24))

    d.text((55, 855), "Número de referencia / operación", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 890), referencia, fill="#2A2A2A", font=fnt("arial_bold", 24))

    d.text((55, 955), "Concepto", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 990), "Varios", fill="#2A2A2A", font=fnt("arial", 24))

    d.text((55, 1180), "Este documento sirve como constancia oficial de la operación efectuada.",
           fill="#9E9E9E", font=fnt("arial", 18))
    d.text((55, 1210), "BBVA Argentina S.A.", fill="#9E9E9E", font=fnt("arial", 18))

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("BBVA Francés", dat, referencia=referencia,
                          ocultos=["cuit_emisor", "cbu_cvu_emisor", "banco_receptor"])


# ---------------------------------------------------------------------------
# BANCO NACIÓN (BNA+)
# ---------------------------------------------------------------------------
def comp_nacion_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"nacion_saliente_{uid}.jpg"
    dat = _datos_comunes("Banco Nación")
    referencia = f"{random.randint(0, 99999999):08d}"

    W, H = 820, 1400
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # Header celeste con "Transferencia"
    d.rectangle([0, 0, W, 130], fill="#3FA9F5")
    d.polygon([(40, 65), (75, 50), (75, 80)], fill="white")  # flecha back
    d.text((W//2 - 110, 50), "Transferencia",
           fill="white", font=fnt("arial_bold", 32))

    logo_nacion(d, W//2 - 90, 200)

    y = 350
    items = [
        ("Destinatario", dat["nombre_rec"].upper()),
        ("CUIT", dat["cuit_rec"].replace("-", "")),
        ("Monto", f"${fmt_monto_ar(dat['monto'])}"),
        ("CBU", dat["cbu_rec"]),
        ("Banco", dat["banco_rec"].replace("Banco ", "").upper()),
        ("Motivo", "Varios"),
        ("Número de transacción", referencia),
        ("Fecha", f"{fmt_fecha_corta(dat['dt'])} {dat['dt'].strftime('%H:%M:%S')}"),
    ]
    for k, v in items:
        d.text((55, y), k, fill="#2A2A2A", font=fnt("arial_bold", 24))
        d.text((55, y + 36), v, fill="#5E5E5E", font=fnt("arial", 22))
        d.line([(55, y + 86), (W - 55, y + 86)], fill="#EEEEEE", width=1)
        y += 100

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Banco Nación", dat, referencia=referencia,
                          ocultos=["nombre_emisor", "cuit_emisor", "cbu_cvu_emisor"])


# ---------------------------------------------------------------------------
# NARANJA X
# ---------------------------------------------------------------------------
def comp_naranjax_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"naranjax_saliente_{uid}.jpg"
    dat = _datos_comunes("Naranja X")
    referencia = str(uuid.uuid4())
    coelsa = gen_coelsa()

    W, H = 820, 1600
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    logo_naranjax(d, 55, 50)
    d.text((55, 130), "Comprobante de transferencia",
           fill="#1A1A1A", font=fnt("arial_bold", 30))

    # Card "Enviaste"
    d.rounded_rectangle([55, 200, W - 55, 360], radius=24,
                        outline="#E5E5E5", width=1, fill="white")
    d.text((85, 225), "Enviaste", fill="#1A1A1A", font=fnt("arial_bold", 28))
    monto_str = fmt_monto_ar(dat['monto'])
    parte_entera, decimales = monto_str.split(",")
    d.text((85, 270), f"$ {parte_entera}",
           fill="#1A1A1A", font=fnt("arial_bold", 50))
    ancho_ent = d.textlength(f"$ {parte_entera}", font=fnt("arial_bold", 50))
    d.text((85 + ancho_ent + 4, 275), decimales,
           fill="#1A1A1A", font=fnt("arial_bold", 28))
    d.text((85, 330), f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} h",
           fill="#7A7A7A", font=fnt("arial", 20))

    # Card origen
    d.rounded_rectangle([55, 400, W - 55, 660], radius=24,
                        outline="#E5E5E5", width=1, fill="white")
    d.text((85, 425), "Cuenta origen", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.rectangle([85, 470, 125, 510], outline="#F25A22", width=2)
    d.text((92, 477), "NX", fill="#F25A22", font=fnt("arial_bold", 18))
    d.text((140, 470), dat["nombre_emi"], fill="#1A1A1A", font=fnt("arial_bold", 22))
    d.text((140, 500), "Naranja X", fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 540), "CBU", fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 565), dat["cbu_emi"], fill="#1A1A1A", font=fnt("arial", 22))
    d.text((85, 605), "CUIL", fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 630), dat["cuit_emi"], fill="#1A1A1A", font=fnt("arial", 22))

    # Card destino
    d.rounded_rectangle([55, 700, W - 55, 960], radius=24,
                        outline="#E5E5E5", width=1, fill="white")
    d.text((85, 725), "Cuenta destino", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((140, 770), dat["nombre_rec"], fill="#1A1A1A", font=fnt("arial_bold", 22))
    d.text((140, 800), dat["banco_rec"], fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 840), "CBU", fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 865), dat["cbu_rec"], fill="#1A1A1A", font=fnt("arial", 22))
    d.text((85, 905), "CUIL", fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 930), dat["cuit_rec"], fill="#1A1A1A", font=fnt("arial", 22))

    # Card operación
    d.rounded_rectangle([55, 1000, W - 55, 1270], radius=24,
                        outline="#E5E5E5", width=1, fill="white")
    d.text((85, 1025), "Información de la operación",
           fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((85, 1075), "COELSA ID", fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 1105), coelsa, fill="#1A1A1A", font=fnt("arial_bold", 22))
    d.text((85, 1160), "Código de transacción",
           fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 1190), referencia, fill="#1A1A1A", font=fnt("arial", 22))

    d.text((55, 1320),
           "Naranja Digital Compañía Financiera S.A.U es una entidad financiera",
           fill="#9E9E9E", font=fnt("arial", 16))
    d.text((55, 1345),
           "autorizada por el Banco Central de la República Argentina.",
           fill="#9E9E9E", font=fnt("arial", 16))

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Naranja X", dat,
                          referencia=referencia, coelsa_id=coelsa,
                          ocultos=["concepto"])


# ---------------------------------------------------------------------------
# BRUBANK
# ---------------------------------------------------------------------------
def comp_brubank_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"brubank_saliente_{uid}.jpg"
    dat = _datos_comunes("Brubank")
    referencia = str(random.randint(10**9, 10**10 - 1))

    W, H = 820, 1340
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # Header violeta
    d.rectangle([0, 0, W, 280], fill="#5B2D90")
    logo_brubank(d, 55, 55)
    d.text((55, 130), "Transferencia enviada",
           fill="white", font=fnt("arial_bold", 26))
    d.text((55, 175), f"$ {fmt_monto_ar(dat['monto'])}",
           fill="white", font=fnt("arial_bold", 50))

    y = 330
    items = [
        ("Para", dat["nombre_rec"]),
        ("CUIT/CUIL", dat["cuit_rec"]),
        ("Banco", dat["banco_rec"]),
        ("CBU", dat["cbu_rec"]),
        ("Motivo", "Varios"),
        ("Fecha", f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} hs"),
        ("Número de operación", referencia),
    ]
    for k, v in items:
        d.text((55, y), k, fill="#7A7A7A", font=fnt("arial", 22))
        d.text((55, y + 32), v, fill="#1A1A1A", font=fnt("arial_bold", 24))
        d.line([(55, y + 80), (W - 55, y + 80)], fill="#EEEEEE", width=1)
        y += 96

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Brubank", dat, referencia=referencia,
                          ocultos=["nombre_emisor", "cuit_emisor", "cbu_cvu_emisor"])


# ---------------------------------------------------------------------------
# UALÁ
# ---------------------------------------------------------------------------
def comp_uala_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"uala_saliente_{uid}.jpg"
    dat = _datos_comunes("Ualá")
    referencia = str(random.randint(10**9, 10**10 - 1))

    W, H = 820, 1280
    img = Image.new("RGB", (W, H), "#F5F8FA")
    d = ImageDraw.Draw(img)

    logo_uala(d, 55, 55)
    d.text((55, 145), "Transferiste",
           fill="#5E5E5E", font=fnt("arial", 24))
    d.text((55, 185), f"$ {fmt_monto_ar(dat['monto'])}",
           fill="#1A1A1A", font=fnt("arial_bold", 58))
    d.text((55, 270), f"a {dat['nombre_rec']}",
           fill="#1A1A1A", font=fnt("arial_bold", 28))

    d.rounded_rectangle([40, 340, W - 40, 920], radius=20,
                        outline="#DCE4EA", width=1, fill="white")
    y = 370
    items = [
        ("Cuenta destino", dat["banco_rec"]),
        ("CBU", dat["cbu_rec"]),
        ("CUIT/CUIL", dat["cuit_rec"]),
        ("Motivo", "Varios"),
        ("Fecha y hora", f"{fmt_fecha_corta(dat['dt'])} {dat['dt'].strftime('%H:%M')} hs"),
        ("Comprobante N°", referencia),
    ]
    for k, v in items:
        d.text((75, y), k, fill="#7A7A7A", font=fnt("arial", 20))
        d.text((75, y + 30), v, fill="#1A1A1A", font=fnt("arial_bold", 22))
        d.line([(75, y + 76), (W - 75, y + 76)], fill="#EEF2F5", width=1)
        y += 90

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Ualá", dat, referencia=referencia,
                          ocultos=["nombre_emisor", "cuit_emisor", "cbu_cvu_emisor"])


# ---------------------------------------------------------------------------
# PERSONAL PAY
# ---------------------------------------------------------------------------
def comp_personalpay_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"personalpay_saliente_{uid}.jpg"
    dat = _datos_comunes("Personal Pay")
    referencia = str(random.randint(10**9, 10**10 - 1))

    W, H = 820, 1300
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # Header violeta degradé simple
    d.rectangle([0, 0, W, 240], fill="#7B2D9F")
    d.text((55, 55), "personal", fill="white", font=fnt("arial_bold", 32))
    d.text((205, 55), "pay", fill="#FFE066", font=fnt("arial_bold", 32))
    d.text((55, 130), "Enviaste", fill="white", font=fnt("arial", 24))
    d.text((55, 165), f"$ {fmt_monto_ar(dat['monto'])}",
           fill="white", font=fnt("arial_bold", 46))

    y = 290
    items = [
        ("Destinatario", dat["nombre_rec"]),
        ("Banco", dat["banco_rec"]),
        ("CBU/CVU", dat["cbu_rec"]),
        ("CUIT/CUIL", dat["cuit_rec"]),
        ("Concepto", "Varios"),
        ("Fecha", f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} hs"),
        ("N° de operación", referencia),
    ]
    for k, v in items:
        d.text((55, y), k, fill="#7A7A7A", font=fnt("arial", 22))
        d.text((55, y + 32), v, fill="#1A1A1A", font=fnt("arial_bold", 24))
        d.line([(55, y + 80), (W - 55, y + 80)], fill="#EEEEEE", width=1)
        y += 96

    guardar_con_compresion(ruido_whatsapp(img), ruta)
    return str(ruta), _gt("Personal Pay", dat, referencia=referencia,
                          ocultos=["nombre_emisor", "cuit_emisor", "cbu_cvu_emisor"])


# ===========================================================================
# REGISTRO DE TEMPLATES
# ===========================================================================
TEMPLATES = {
    ("Mercado Pago",   "transferencia_saliente"): comp_mp_saliente,
    ("Banco Macro",    "transferencia_saliente"): comp_macro_saliente,
    ("Banco Santander","transferencia_saliente"): comp_santander_saliente,
    ("Banco Galicia",  "transferencia_saliente"): comp_galicia_saliente,
    ("BBVA Francés",   "transferencia_saliente"): comp_bbva_saliente,
    ("Banco Nación",   "transferencia_saliente"): comp_nacion_saliente,
    ("Naranja X",      "transferencia_saliente"): comp_naranjax_saliente,
    ("Brubank",        "transferencia_saliente"): comp_brubank_saliente,
    ("Ualá",           "transferencia_saliente"): comp_uala_saliente,
    ("Personal Pay",   "transferencia_saliente"): comp_personalpay_saliente,
}

# Cuántas veces aparece cada banco, en proporción a los 51 comprobantes REALES
# ya revisados a mano. Medido sobre la base el 2026-08-07:
#
#   Mercado Pago 25 (49%) · Macro 8 · Galicia 6 · Santander 5
#   Nación 2 · Naranja X 2 · Brubank 1 · (BBVA, Ualá, Personal Pay: 0)
#
# Generar 10% de cada banco —lo que se hacía antes— le enseña en partes iguales
# algo que en la realidad es mitad Mercado Pago, y le da el mismo peso a tres
# bancos que en este negocio nunca aparecieron. A los que no aparecen se les
# deja peso 1 y no 0: si mañana entra uno, el modelo ya vio el formato.
PESOS = {
    "Mercado Pago": 25, "Banco Macro": 8, "Banco Galicia": 6, "Banco Santander": 5,
    "Banco Nación": 2, "Naranja X": 2, "Brubank": 1,
    "BBVA Francés": 1, "Ualá": 1, "Personal Pay": 1,
}


# ===========================================================================
# EL DATASET
# ===========================================================================
sys.path.insert(0, str(AQUI))
from extraer import CAMPOS, PROMPT_V3  # noqa: E402

# El prompt de entrenamiento es el MISMO con el que se infiere. Entrenar con uno
# y medir con otro invalidaría la comparación zero-shot vs fine-tuned de F10.
PROMPT = PROMPT_V3


def verificar(gt: dict) -> None:
    """Que la etiqueta esté canónica. Es el chequeo que faltó la vez pasada.

    El intento anterior entrenó con montos en formato argentino y CUIT con
    guiones sin que nada se quejara: el error recién se habría visto en el
    número final de F10, ya sin forma de saber de dónde salía.
    """
    assert list(gt) == CAMPOS, f"claves fuera de orden: {list(gt)}"
    assert re.fullmatch(r"\d+\.\d{2}", gt["monto"]), f"monto {gt['monto']!r}"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", gt["fecha"]), f"fecha {gt['fecha']!r}"

    # null es una respuesta VÁLIDA y no una falla: significa "no está en la
    # imagen". Antes estas cuatro líneas exigían valor y por eso blindaban el
    # bug de las etiquetas inventadas en vez de agarrarlo — un template que no
    # dibujaba el CUIT del emisor pasaba igual, porque el CUIT estaba puesto.
    def opcional(campo, patron):
        assert gt[campo] is None or re.fullmatch(patron, gt[campo]), \
            f"{campo} {gt[campo]!r}"

    opcional("hora", r"\d{2}:\d{2}")
    for c in ("cuit_emisor", "cuit_receptor"):
        opcional(c, r"\d{11}")
    for c in ("cbu_cvu_emisor", "cbu_cvu_receptor"):
        opcional(c, r"\d{22}")
    opcional("coelsa_id", r"[0-9A-Z]{22}")


def ejemplo(plantilla) -> dict:
    """Un registro en el formato que lee mlx_vlm.trainer.Dataset de 0.1.15.

    Las claves son `images` y `messages` — verificado leyendo el código
    instalado, no la documentación.

    `content` va como STRING PLANO, y esto es lo contrario de lo que parece.
    Verificado corriendo las dos formas por el camino real de `lora.py`:

      · lora.py aplica `mlx_vlm.prompt_utils.apply_chat_template` por default
        (su flag --apply-chat-template es action="store_false", así que está al
        revés del nombre: pasarlo lo DESACTIVA).
      · Ese wrapper no respeta el content que recibe: lo reconstruye con
        `get_message_json`, que envuelve p["content"] en {"type":"text","text":…}
        y agrega el {"type":"image"} por su cuenta.
      · Si le pasás una lista de dicts queda ANIDADA, y la etiqueta que el
        modelo aprende a emitir termina siendo la repr de Python de una lista:
        [{'type': 'text', 'text': '{…json…}'}] en vez del JSON limpio.

    El token de imagen entra igual en las dos formas —lo pone el wrapper—, así
    que este error no se nota mirando los input_ids: se nota mirando el texto.
    """
    ruta, gt = plantilla()
    verificar(gt)
    return {
        "images": [ruta],
        "messages": [
            {"role": "user", "content": PROMPT},
            {"role": "assistant", "content": json.dumps(gt, ensure_ascii=False)},
        ],
    }


# Qué tiene que aparecer en el código de dibujo de un template para que ese
# campo sea legible en la imagen que produce.
_MARCAS_DIBUJO = {
    "fecha":            [r"fmt_fecha", r"%d/%m", r"%Y-%m-%d"],
    "hora":             [r"%H:%M"],
    "nombre_emisor":    [r"nombre_emi"],
    "cuit_emisor":      [r"cuit_emi"],
    "cbu_cvu_emisor":   [r"cbu_emi"],
    "nombre_receptor":  [r"nombre_rec"],
    "cuit_receptor":    [r"cuit_rec"],
    "cbu_cvu_receptor": [r"cbu_rec"],
    "banco_receptor":   [r"banco_rec"],
    "concepto":         [r"Concepto", r"Motivo"],
    "referencia":       [r"referencia"],
}


def verificar_templates() -> None:
    """Que lo que cada template DECLARA como oculto sea lo que de verdad no dibuja.

    Es el chequeo que faltaba y por el que el primer dataset salió envenenado:
    `_gt` emitía los 16 campos siempre, así que 270 de 300 ejemplos le enseñaban
    al modelo a inventar algo —el `cuit_emisor` en 240 de ellos— y ni los 7
    asserts de `verificar()` ni mirar las imágenes lo mostraban, porque cada
    etiqueta por separado estaba perfectamente bien formada.

    Lee el código fuente de este mismo archivo: si alguien agrega un campo a un
    template o saca uno, la declaración deja de coincidir y esto se queja. Sin
    esto, `ocultos` se desactualiza en silencio, que es exactamente cómo nació
    el bug original.
    """
    import ast
    fuente = Path(__file__).read_text(encoding="utf-8")
    problemas = []
    for nodo in ast.parse(fuente).body:
        if not (isinstance(nodo, ast.FunctionDef) and nodo.name.startswith("comp_")):
            continue
        cuerpo = ast.get_source_segment(fuente, nodo)
        # el `return ... _gt(...)` nombra variables que no son dibujo
        dibujo = re.sub(r"return\s+str\(ruta\).*", "", cuerpo, flags=re.S)
        declarados = set(re.findall(r'"([a-z_]+)"', re.search(
            r"ocultos=\[(.*?)\]", cuerpo, re.S).group(1))) \
            if "ocultos=" in cuerpo else set()
        reales = {c for c, pats in _MARCAS_DIBUJO.items()
                  if not any(re.search(p, dibujo) for p in pats)}
        # coelsa_id ya se pasa explícito, no entra por `ocultos`
        if reales - declarados:
            problemas.append(f"{nodo.name}: NO dibuja {sorted(reales - declarados)} "
                             f"pero la etiqueta los llena")
        if declarados - reales:
            problemas.append(f"{nodo.name}: declara ocultos {sorted(declarados - reales)} "
                             f"pero sí los dibuja")
    assert not problemas, "templates y etiquetas no coinciden:\n  " + "\n  ".join(problemas)


def main() -> None:
    p = argparse.ArgumentParser(description="Genera el dataset sintético de F8.")
    p.add_argument("--n", type=int, default=4,
                   help="ejemplos totales, repartidos en partes iguales entre los 10 bancos")
    p.add_argument("--semilla", type=int, default=42)
    p.add_argument("--salida", type=Path, default=SALIDA_DIR / "train.jsonl")
    args = p.parse_args()

    verificar_templates()   # antes de generar nada: si no coinciden, no se genera

    random.seed(args.semilla)
    Faker.seed(args.semilla)

    # La bolsa repite cada banco según su peso, y después se recorre en orden:
    # así la proporción sale exacta y no librada al azar de 300 tiradas.
    bolsa = [f for (banco, _), f in TEMPLATES.items() for _ in range(PESOS[banco])]
    registros = [ejemplo(bolsa[i % len(bolsa)]) for i in range(args.n)]
    random.shuffle(registros)

    args.salida.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in registros),
        encoding="utf-8",
    )
    print(f"{len(registros)} ejemplos → {args.salida}")
    print(f"imágenes → {OUT_DIR}")


if __name__ == "__main__":
    main()

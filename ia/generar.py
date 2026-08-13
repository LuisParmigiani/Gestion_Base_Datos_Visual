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
  5. (2026-08-11) La etiqueta ya no se declara: la arma `Lienzo`, que anota qué
     campos se dibujaron y con qué texto, y `_gt` verifica las dos direcciones
     contra la imagen. Antes había una lista `ocultos=[...]` escrita a mano que
     se despegó del dibujo dos veces sin que nada se quejara.
  6. (2026-08-11) Se dibuja a ESCALA y se entrega achicado: la mitad nítida y la
     mitad degradada con severidad continua. Ver `finalizar()`.

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

sys.path.insert(0, str(AQUI))
from extraer import CAMPOS, PROMPT_V3  # noqa: E402

# El prompt de entrenamiento es el MISMO con el que se infiere. Entrenar con uno
# y medir con otro invalidaría la comparación zero-shot vs fine-tuned de F10.
PROMPT = PROMPT_V3

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


# Todo se dibuja al doble y se baja al guardar. El texto queda suavizado como en
# un screenshot de verdad —los celulares renderizan a 2x o 3x y bajan— en vez de
# con el borde duro de dibujar directo al tamaño final.
#
# ⚠️ Lo que NO se puede es entregar la imagen grande. Medido con el procesador
# instalado (Qwen2VLImageProcessor, 28x28 px por token, sin resize a tamaño
# fijo): 820x1340 son 1.392 tokens y 1640x2680 son 5.664. El tope probado del
# entrenamiento es 1.848, y 3.078 mató dos corridas sin dejar traceback.
# Por eso `finalizar()` SIEMPRE achica.
ESCALA = 2
ANCHO_ENTREGA = 820


def fnt(familia: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FUENTES[familia], size * ESCALA)


# ---------------------------------------------------------------------------
# EL LIENZO — una sola verdad sobre qué campos están en la imagen
# ---------------------------------------------------------------------------
class Lienzo:
    """`ImageDraw` que además anota TODO el texto que dibuja.

    Antes había dos verdades sobre cada plantilla: el código que dibujaba, y una
    lista `ocultos=[...]` escrita a mano al lado del `return`. Se separaron en
    silencio dos veces —Mercado Pago etiquetaba `hora: null` con la hora escrita
    en la imagen, y pesa la mitad del dataset— y el chequeo que existía no podía
    verlo: leía el código fuente con regex y la hora entraba por un helper.

    Con esto `ocultos` deja de escribirse: sale de restar los campos registrados
    contra los 16. Y como queda el texto realmente dibujado, `_gt` puede
    verificar las dos direcciones —lo etiquetado está en la imagen, y lo que
    está en la imagen no queda en null— que es la única prueba que no depende
    de cómo esté escrito el código.
    """

    # Las que reciben la geometría en el primer argumento y hay que escalar.
    _GEOMETRICOS = {"line", "rectangle", "rounded_rectangle", "ellipse",
                    "polygon", "arc", "chord", "pieslice"}

    def __init__(self, d: ImageDraw.ImageDraw, escala: int = 1) -> None:
        self._d = d
        self.escala = escala
        self.dibujado: list[str] = []
        self.visto: set[str] = set()

    def _escalar(self, v):
        """Las plantillas siguen escritas en coordenadas de 820 de ancho: acá se
        multiplican. Sirve para (x, y), para [x0, y0, x1, y1] y para la lista de
        puntos de un polígono."""
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v * self.escala
        if isinstance(v, (list, tuple)):
            return type(v)(self._escalar(x) for x in v)
        return v

    def __getattr__(self, nombre):        # line, rectangle, textlength, ...
        atributo = getattr(self._d, nombre)
        if nombre not in self._GEOMETRICOS:
            return atributo

        def envuelto(xy, *a, **kw):
            for k in ("width", "radius"):
                if k in kw:
                    kw[k] = max(1, int(kw[k] * self.escala))
            return atributo(self._escalar(xy), *a, **kw)
        return envuelto

    def textlength(self, texto, *a, **kw) -> float:
        # La fuente ya viene escalada, así que esto mide en píxeles finales; las
        # plantillas lo usan para posicionar, o sea que esperan los suyos.
        return self._d.textlength(texto, *a, **kw) / self.escala

    def text(self, xy, texto, *a, **kw) -> None:
        self.dibujado.append(str(texto))
        self._d.text(self._escalar(xy), texto, *a, **kw)

    def campo(self, campos, xy, texto, *a, leido: Optional[str] = None, **kw) -> None:
        """Dibuja y registra. `campos` es un nombre, varios (una fecha larga
        lleva la fecha Y la hora en la misma cadena) o None: hay filas que se
        dibujan y no son ninguno de los 16 ("Plazo de acreditación").

        `leido` es lo que una persona LEE cuando el valor queda partido en dos
        dibujos — Naranja X escribe los centavos aparte y en chico.
        """
        if campos:
            self.visto.update({campos} if isinstance(campos, str) else set(campos))
        self._d.text(self._escalar(xy), texto, *a, **kw)
        self.dibujado.append(str(texto if leido is None else leido))

    def visible(self, *campos: str) -> None:
        """Para lo que se lee en la imagen pero no sale de un `text` con el
        valor crudo: el banco emisor lo dice el LOGO, el tipo de operación lo
        dice el título, la moneda la dice el símbolo."""
        self.visto.update(campos)

    def logo(self, dibujar, x: int, y: int) -> None:
        """El logo es la prueba de quién emitió: dibujarlo registra
        `banco_emisor`. Así una plantilla nueva no puede olvidarse."""
        self.visible("banco_emisor")
        dibujar(self, x, y)


# ---------------------------------------------------------------------------
# HELPERS DE DATOS ARGENTINOS
# ---------------------------------------------------------------------------
MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_ES = ["lunes", "martes", "miércoles", "jueves",
           "viernes", "sábado", "domingo"]


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


# Cuántos dígitos enteros tiene un monto, con las proporciones MEDIDAS el 2026-08-12
# sobre los 2822 movimientos del extracto real: 3 dígitos 1,0% · 4 dígitos 27,9% ·
# 5 dígitos 60,2% · 6 dígitos 9,6% · 7 dígitos 1,3%. Coinciden con los 62 comprobantes
# revisados a mano (25,8% y 62,9%), así que el extracto sirve para calibrar.
#
# Antes esto era `uniform(500, 350_000)`, que por ser uniforme deja el 72% en 6 dígitos:
# el modelo se entrenó esperando cientos de miles donde la realidad son decenas de miles,
# y ante una imagen dudosa caía en ese sesgo (28.000 leído como 1.126.081,9).
_DIGITOS_MONTO = [3] + [4] * 28 + [5] * 60 + [6] * 10 + [7]


def gen_monto() -> float:
    """Un importe con la forma que tienen los importes de verdad.

    Medido sobre las mismas 2822 filas: el 90,3% no tiene centavos, el 89,4% termina
    en `00` y el 48,8% en `000`. Un generador que reparte centavos al azar le enseña
    al modelo a esperar decimales que casi nunca existen.
    """
    digitos = random.choice(_DIGITOS_MONTO)
    monto = random.uniform(10 ** (digitos - 1), 10 ** digitos)
    if random.random() >= 0.90:
        return round(monto, 2)                      # el 10% que sí lleva centavos
    if monto >= 10_000 and random.random() < 0.60:
        return float(round(monto, -3))
    return float(round(monto, -2))


def gen_fecha_hora_reciente() -> datetime:
    # Hasta 2026-08-12 esto era `randint(0, 60)`: las 800 sintéticas caían en una ventana
    # de dos meses y sólo había 61 fechas distintas. El modelo aprendió el año y el mes
    # en vez de leerlos — en 044.jpeg, con la verdad en 2023, contestó 2026. El rango va
    # ancho a propósito: lo que fuerza a LEER una fecha es no poder adivinarla.
    dias = random.randint(0, 365) if random.random() < 0.70 else random.randint(0, 1460)
    base = datetime.now() - timedelta(days=dias)
    return base.replace(
        hour=random.randint(6, 23),
        minute=random.randint(0, 59),
        second=0,
        microsecond=0,
    )


# Cuántas palabras tiene un nombre, MEDIDO el 2026-08-12 sobre los 108 nombres de emisor
# y receptor de los 62 comprobantes revisados: 1 palabra 0,9% · 2 → 11,1% · 3 → 49,1% ·
# 4 → 7,4% · 5 → 31,5%. Son más largos de lo que uno supone, y por eso se midieron.
_PALABRAS_NOMBRE = [1] + [2] * 11 + [3] * 49 + [4] * 7 + [5] * 32


def nombre_persona() -> str:
    """Un nombre con la cantidad de palabras que tienen los nombres de verdad.

    Se arma pieza por pieza en vez de usar `fake.name()` porque ésa mezcla nombres de
    pila dentro de los apellidos (devuelve "Thiago Lionel Ledesma Herrera") y no deja
    elegir el largo. `first_name()` y `last_name()` sí tienen los dos pools separados.
    """
    palabras = random.choice(_PALABRAS_NOMBRE)
    de_pila = 1 if palabras <= 2 else random.choice([1, 2])
    partes = [fake.first_name().split()[0] for _ in range(de_pila)]
    partes += [fake.last_name().split()[0] for _ in range(palabras - de_pila)]
    return " ".join(partes).title()


def banco_destino_random(excluir: Optional[str] = None) -> str:
    candidatos = [b for b in CBU_PREFIJOS if b != excluir]
    return random.choice(candidatos)


# Hasta 2026-08-11 el concepto era la constante "Varios" en las 300 sintéticas:
# el modelo no podía aprender a LEER un concepto, solo a ESCRIBIR "Varios". Y es
# el campo que le pone el techo a la meta del 98%, porque es texto libre.
CONCEPTOS = [
    "Varios", "Alquiler", "Honorarios", "Pago de servicios", "Préstamo",
    "Expensas", "Sueldo", "Compra", "Devolución", "Anticipo", "Cuota",
    "Pago proveedor", "Reintegro", "Seña", "Materiales",
]


# ---------------------------------------------------------------------------
# LOS DOS PERFILES DE CALIDAD
# ---------------------------------------------------------------------------
# La mitad del dataset sale nítida y la otra mitad maltratada, y dentro de la
# mitad maltratada la severidad es CONTINUA: no hay dos degradadas iguales, van
# desde "se nota apenas" hasta "captura de pantalla de una captura reenviada
# tres veces". Sin variedad el modelo aprende un único nivel de ruido.
NITIDO, DEGRADADO = "nitido", "degradado"
_perfil = NITIDO          # lo fija `ejemplo()` antes de llamar a la plantilla


def _a_ancho(img: Image.Image, ancho: int) -> Image.Image:
    return img.resize((ancho, round(img.height * ancho / img.width)), Image.LANCZOS)


def finalizar(img: Image.Image, ruta: Path) -> None:
    """Baja la imagen dibujada en grande al tamaño de entrega y la guarda.

    ⚠️ El tamaño FINAL es lo único que decide cuántos tokens consume el modelo
    (ver el comentario de ESCALA). Los dos caminos achican; ninguno entrega la
    imagen a 2x.
    """
    if _perfil == NITIDO:
        # Bajar de 2x con LANCZOS es lo que da el suavizado: el texto queda como
        # el de un screenshot real, no con el borde duro de dibujar al tamaño.
        finalizada = _a_ancho(img, ANCHO_ENTREGA)
        calidad = random.randint(90, 97)
    else:
        # El piso está puesto a propósito y no es "lo peor que se puede ver": si
        # el CBU de 22 dígitos queda ilegible, la etiqueta le estaría enseñando
        # al modelo a escribir un número que la imagen NO muestra. Es el mismo
        # error que `_gt` persigue, entrando por la puerta de la calidad.
        severidad = random.random()          # 0 = apenas se nota · 1 = el piso legible
        if random.random() < 0.35:
            img = img.rotate(random.uniform(-2.5, 2.5), resample=Image.BICUBIC,
                             expand=True, fillcolor=(245, 245, 245))
        finalizada = _a_ancho(img, round(760 - severidad * 280))       # 760 → 480
        if severidad > 0.15:
            finalizada = finalizada.filter(
                ImageFilter.GaussianBlur(radius=severidad * 0.9))
        calidad = round(72 - severidad * 40)                            # 72 → 32

    finalizada.convert("RGB").save(ruta, "JPEG", quality=calidad, optimize=True)


def lienzo_nuevo(W: int, H: int, fondo="white") -> Tuple[Image.Image, "Lienzo"]:
    """La plantilla sigue escribiendo coordenadas de 820 de ancho; acá se
    multiplican por ESCALA y nadie más se entera."""
    img = Image.new("RGB", (W * ESCALA, H * ESCALA), fondo)
    return img, Lienzo(ImageDraw.Draw(img), ESCALA)


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
def fila_kv_izq_der(d, y, w, label, valor, campos=None, *,
                    color_label="#6E6E6E", color_valor="#1A1A1A",
                    f_label=None, f_valor=None,
                    margen=50, con_linea=True):
    f_label = f_label or fnt("arial", 22)
    f_valor = f_valor or fnt("arial_bold", 22)
    d.text((margen, y), label, fill=color_label, font=f_label)
    ancho_v = d.textlength(valor, font=f_valor)
    d.campo(campos, (w - margen - ancho_v, y), valor, fill=color_valor, font=f_valor)
    if con_linea:
        d.line([(margen, y + 42), (w - margen, y + 42)], fill="#EEEEEE", width=1)


# ===========================================================================
#                              TEMPLATES POR BANCO
# ===========================================================================
def _datos_comunes(banco_emisor: str) -> dict:
    """Genera el set de datos que comparten todos los templates."""
    dt = gen_fecha_hora_reciente()
    monto = gen_monto()
    nombre_emi = nombre_persona()
    nombre_rec = nombre_persona()
    cuit_emi = gen_cuit_ar()
    cuit_rec = gen_cuit_ar()
    cbu_emi = gen_cbu(banco_emisor)
    banco_rec = banco_destino_random(excluir=banco_emisor)
    cbu_rec = gen_cbu(banco_rec)
    return {
        "dt": dt, "monto": monto,
        "concepto": random.choice(CONCEPTOS),
        "nombre_emi": nombre_emi, "nombre_rec": nombre_rec,
        "cuit_emi": cuit_emi, "cuit_rec": cuit_rec,
        "cbu_emi": cbu_emi, "cbu_rec": cbu_rec,
        "banco_rec": banco_rec,
    }


def solo_digitos(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


# Los cuatro campos que ninguna plantilla escribe como valor crudo: la fecha va
# en formato argentino (`05/08/2026`) contra el canónico `2026-08-05`, el banco
# emisor lo dice el logo, el tipo de operación lo dice el título y la moneda la
# dice el símbolo. Se declaran con `lienzo.visible()` y quedan fuera del cotejo
# literal; los otros doce tienen que aparecer tal cual en la imagen.
_NO_LITERALES = {"fecha", "banco_emisor", "tipo_operacion", "moneda"}


# Un "número" tal como se ve escrito, con sus separadores: `20-27705919-4`,
# `275.054,91`, `05/08/2026`, `19:21`. Arranca en dígito para no comerse el `$`.
_NUMERO_ESCRITO = re.compile(r"\d[\d.,:/\-]*")


def _en_la_imagen(valor: str, dibujado: Sequence[str], con_digitos: bool = True) -> bool:
    """¿Este valor se lee en la imagen? Primero como texto; si no, por dígitos.

    El cotejo por dígitos es el que importa: la etiqueta dice `20277059194` y la
    imagen `20-27705919-4`; el monto va `275054.91` contra `$ 275.054,91`.

    Compara NÚMERO COMPLETO, no subcadena, y ese detalle no es cosmético: con
    subcadenas, la hora `11:07` "aparecía" dentro de `CTA $ 811-075716/5` porque
    sus dígitos contienen `1107`, y el generador se plantaba con un error falso.
    """
    if any(valor.casefold() in t.casefold() for t in dibujado):
        return True
    if not con_digitos:
        return False
    v_dig = solo_digitos(valor)
    return bool(v_dig) and any(
        solo_digitos(numero) == v_dig
        for t in dibujado for numero in _NUMERO_ESCRITO.findall(t)
    )


def _gt(banco_emisor: str, datos: dict, lienzo: "Lienzo", *,
        referencia: str, coelsa_id: Optional[str] = None) -> dict:
    """La etiqueta, en formato CANÓNICO — no en el que muestra la imagen.

    La imagen dice `$ 275.054,91` y `20-53594652-7`; la etiqueta dice
    `275054.91` y `20535946527`. Esa traducción es lo que el fine-tuning tiene
    que aprender, y es la que `web/src/lib/motor.ts` necesita para conciliar.

    **La etiqueta describe la imagen, no los datos con que se generó.** Un
    comprobante del Santander no muestra el CUIT del emisor; etiquetarlo igual
    le enseña al modelo a inventar un CUIT de 11 dígitos que pasa cualquier
    validación de formato. Es el peor error posible en este proyecto, porque
    acusa a un cliente honesto con un dato que parece perfectamente válido.

    Esa regla ya no se declara a mano: los campos ocultos son los que nadie
    registró en el lienzo, y las dos direcciones se verifican contra el texto
    que de verdad se dibujó.
    """
    monto = round(datos["monto"], 2)
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
        "moneda": "ARS",   # el proyecto es solo pesos, por decisión del usuario
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
        "concepto": datos["concepto"],
        "referencia": referencia,
        "coelsa_id": coelsa_id,
    }
    assert list(etiqueta) == CAMPOS, f"claves fuera de orden: {list(etiqueta)}"

    ocultos = set(CAMPOS) - lienzo.visto
    for campo in sorted(set(CAMPOS) - _NO_LITERALES):
        # `hora` se dibuja siempre como `HH:MM`, igual que la etiqueta: no
        # necesita el cotejo por dígitos y con 4 dígitos sueltos es el único que
        # puede chocar por casualidad contra un número de cuenta.
        valor = etiqueta[campo]
        esta = _en_la_imagen(valor or "", lienzo.dibujado, con_digitos=campo != "hora")
        if valor is not None and campo in ocultos and esta:
            raise AssertionError(
                f"{banco_emisor}: `{campo}` se lee en la imagen ({valor!r}) y la "
                f"etiqueta lo deja en null — falta registrarlo con lienzo.campo()")
        if valor is not None and campo not in ocultos and not esta:
            raise AssertionError(
                f"{banco_emisor}: `{campo}` se etiqueta {valor!r} pero eso NO se "
                f"lee en la imagen — la etiqueta le enseña a inventar")
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
    img, d = lienzo_nuevo(W, H, "white")

    if random.random() < 0.55:
        wm = Image.new("RGBA", (W * ESCALA, H * ESCALA), (0, 0, 0, 0))
        # Lienzo aparte a propósito: la marca de agua no es ninguno de los 16
        # campos, así que su texto no tiene que entrar en el cotejo.
        Lienzo(ImageDraw.Draw(wm), ESCALA).text((-30, H//2 - 200), "ACREDITADA",
                                                fill=(220, 232, 245, 120),
                                                font=fnt("arial_bold", 150))
        wm = wm.rotate(-22, resample=Image.BICUBIC)
        img.paste(wm, (0, 0), wm)

    d.logo(logo_mp, 55, 65)
    d.campo("tipo_operacion", (55, 175), "Comprobante de transferencia",
            fill="#1A1A1A", font=fnt("arial_bold", 38))
    # La fecha larga termina en "a las 14:35 hs": trae la fecha Y la hora. Que
    # acá dijera solo `fecha` es lo que dejó 150 ejemplos enseñando a no leer
    # una hora que está escrita.
    d.campo(("fecha", "hora"), (55, 230), fmt_fecha_larga_ar(dat["dt"]),
            fill="#7A7A7A", font=fnt("arial", 22))
    d.line([(55, 280), (W - 55, 280)], fill="#E5E5E5", width=1)

    d.campo(("monto", "moneda"), (55, 320), f"$ {fmt_monto_ar(dat['monto'])}",
            fill="#1A1A1A", font=fnt("arial_bold", 64))
    d.campo("concepto", (55, 410), f"Motivo: {dat['concepto']}",
            fill="#7A7A7A", font=fnt("arial", 22))

    y_de = 495
    d.ellipse([48, y_de, 64, y_de + 16], fill="#00B1EA")
    d.line([(56, y_de + 16), (56, y_de + 220)], fill="#00B1EA", width=2)
    d.text((90, y_de - 6), "De", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("nombre_emisor", (90, y_de + 24), dat["nombre_emi"], fill="#1A1A1A", font=fnt("arial_bold", 26))
    d.campo("cuit_emisor", (90, y_de + 62), f"CUIT/CUIL: {dat['cuit_emi']}", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("banco_emisor", (90, y_de + 94), "Mercado Pago", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("cbu_cvu_emisor", (90, y_de + 126), f"CVU: {dat['cbu_emi']}", fill="#7A7A7A", font=fnt("arial", 22))

    y_pa = y_de + 230
    d.ellipse([48, y_pa, 64, y_pa + 16], fill="#00B1EA")
    d.text((90, y_pa - 6), "Para", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("nombre_receptor", (90, y_pa + 24), dat["nombre_rec"], fill="#1A1A1A", font=fnt("arial_bold", 26))
    d.campo("cuit_receptor", (90, y_pa + 62), f"CUIT/CUIL: {dat['cuit_rec']}", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("banco_receptor", (90, y_pa + 94), dat["banco_rec"], fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("cbu_cvu_receptor", (90, y_pa + 126), f"CVU: {dat['cbu_rec']}", fill="#7A7A7A", font=fnt("arial", 22))

    y_ref = y_pa + 210
    d.line([(55, y_ref), (W - 55, y_ref)], fill="#E5E5E5", width=1)
    d.text((55, y_ref + 30), "Número de operación de Mercado Pago",
           fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("referencia", (55, y_ref + 62), referencia, fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((55, y_ref + 110), "Código de identificación",
           fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("coelsa_id", (55, y_ref + 142), cod_id, fill="#1A1A1A", font=fnt("arial_bold", 24))

    finalizar(img, ruta)
    return str(ruta), _gt("Mercado Pago", dat, d,
                          referencia=referencia, coelsa_id=cod_id)


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
    img, d = lienzo_nuevo(W, H, "white")

    # Header lavanda
    d.rectangle([0, 0, W, 320], fill="#E8E8F5")
    d.logo(logo_macro, W//2 - 60, 50)
    d.text((90, 160), "Comprobante de", fill="#1A1A1A", font=fnt("arial_bold", 44))
    d.campo("tipo_operacion", (90, 215), "transferencia", fill="#1A1A1A", font=fnt("arial_bold", 44))

    # Datos de transferencia
    d.text((50, 370), "Datos de transferencia",
           fill="#1B2A6B", font=fnt("arial_bold", 28))

    y = 430
    d.text((50, y), "Para", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.campo("nombre_receptor", (50, y + 36), dat["nombre_rec"], fill="#1A1A1A", font=fnt("arial", 24))
    d.text((50, y + 80), "Cuenta:", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.campo("banco_receptor", (50, y + 116),
            f"{dat['banco_rec']} - CA ARS {random.randint(1000, 9999)}",
            fill="#1A1A1A", font=fnt("arial", 24))
    d.text((50, y + 160), "CUIL/CUIT:", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.campo("cuit_receptor", (50, y + 196), dat["cuit_rec"].replace("-", ""),
            fill="#1A1A1A", font=fnt("arial", 24))

    d.line([(50, y + 260), (W - 50, y + 260)], fill="#EFEFEF", width=1)

    y2 = y + 290
    d.text((50, y2), "Desde", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.campo("nombre_emisor", (50, y2 + 36), dat["nombre_emi"], fill="#1A1A1A", font=fnt("arial", 24))
    d.text((50, y2 + 80), "Cuenta:", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.campo("banco_emisor", (50, y2 + 116),
            f"Banco Macro - CA $ {random.randint(1000, 9999)}",
            fill="#1A1A1A", font=fnt("arial", 24))
    d.text((50, y2 + 160), "CUIL/CUIT:", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.campo("cuit_emisor", (50, y2 + 196), dat["cuit_emi"].replace("-", ""),
            fill="#1A1A1A", font=fnt("arial", 24))

    d.line([(50, y2 + 260), (W - 50, y2 + 260)], fill="#EFEFEF", width=1)

    y3 = y2 + 290
    for i, (k, v, c) in enumerate([
        ("Monto:", f"$ {fmt_monto_ar(dat['monto'])}", ("monto", "moneda")),
        ("Concepto:", dat["concepto"], "concepto"),
        ("N° de operación:", referencia, "referencia"),
        ("Fecha y hora:", f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} h",
         ("fecha", "hora")),
        ("ID COELSA:", coelsa, "coelsa_id"),
    ]):
        d.text((50, y3 + i*86), k, fill="#1A1A1A", font=fnt("arial_bold", 22))
        d.campo(c, (50, y3 + i*86 + 32), v, fill="#1A1A1A", font=fnt("arial", 22))

    finalizar(img, ruta)
    return str(ruta), _gt("Banco Macro", dat, d,
                          referencia=referencia, coelsa_id=coelsa)


# ---------------------------------------------------------------------------
# SANTANDER
# ---------------------------------------------------------------------------
def comp_santander_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"santander_saliente_{uid}.jpg"
    dat = _datos_comunes("Banco Santander")
    referencia = str(random.randint(10**7, 10**8 - 1))

    W, H = 820, 1500
    img, d = lienzo_nuevo(W, H, "white")

    d.logo(logo_santander, W//2 - 130, 50)
    d.campo("tipo_operacion", (50, 170), "Comprobante de Transferencia",
            fill="#1A1A1A", font=fnt("arial_bold", 36))
    d.line([(50, 240), (W - 50, 240)], fill="#E5E5E5", width=1)

    # El Santander no muestra nada del emisor salvo el logo, ni el CUIT ni el
    # banco del destinatario: la "Cuenta débito" es un número de cuenta, no un
    # CBU. Todo eso queda en null porque nadie lo registra.
    filas = [
        ("Importe debitado", f"$ {fmt_monto_ar(dat['monto'])}", ("monto", "moneda")),
        ("Cuenta destino", dat["cbu_rec"], "cbu_cvu_receptor"),
        ("Titular cuenta destino", dat["nombre_rec"], "nombre_receptor"),
        ("Cuenta débito", f"CTA $ {random.randint(100, 999)}-{random.randint(100000, 999999)}/{random.randint(0, 9)}", None),
        ("Concepto transferencia", dat["concepto"], "concepto"),
        ("Información adicional", "-", None),
        ("Plazo de acreditación", "Inmediato", None),
        ("Fecha de ejecución", fmt_fecha_corta(dat["dt"]), "fecha"),
        ("N° comprobante", referencia, "referencia"),
    ]
    y = 290
    for lbl, val, campos in filas:
        fila_kv_izq_der(d, y, W, lbl, val, campos)
        y += 90

    # Disclaimer al pie
    d.text((50, y + 60),
           "Recuerde que puede consultar e imprimir este comprobante ingresando al",
           fill="#7A7A7A", font=fnt("arial", 18))
    d.text((50, y + 86),
           "módulo de Pagos y Transferencias en Online Banking Personas.",
           fill="#7A7A7A", font=fnt("arial", 18))

    finalizar(img, ruta)
    return str(ruta), _gt("Banco Santander", dat, d, referencia=referencia)


# ---------------------------------------------------------------------------
# GALICIA
# ---------------------------------------------------------------------------
def comp_galicia_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"galicia_saliente_{uid}.jpg"
    dat = _datos_comunes("Banco Galicia")
    referencia = str(random.randint(10**5, 10**6 - 1))

    W, H = 820, 1340
    img, d = lienzo_nuevo(W, H, "white")

    d.logo(logo_galicia, 55, 55)
    d.campo("tipo_operacion", (55, 130), "Comprobante de transferencia",
            fill="#2A2A2A", font=fnt("arial_bold", 32))
    d.line([(55, 195), (W - 55, 195)], fill="#E5E5E5", width=1)

    d.text((55, 225), "Importe", fill="#7A7A7A", font=fnt("arial", 24))
    d.campo(("monto", "moneda"), (55, 265), f"$ {fmt_monto_ar(dat['monto'])}",
            fill="#2A2A2A", font=fnt("arial_bold", 38))
    d.line([(55, 340), (W - 55, 340)], fill="#EFEFEF", width=1)

    d.text((55, 370), "Destino", fill="#7A7A7A", font=fnt("arial", 24))
    d.campo("nombre_receptor", (55, 410), dat["nombre_rec"], fill="#2A2A2A", font=fnt("arial_bold", 28))
    d.campo("cbu_cvu_receptor", (55, 455), f"CBU/CVU: {dat['cbu_rec']}", fill="#2A2A2A", font=fnt("arial", 22))
    d.campo("cuit_receptor", (55, 495), f"CUIT/CUIL: {dat['cuit_rec']}", fill="#7A7A7A", font=fnt("arial", 22))
    d.line([(55, 560), (W - 55, 560)], fill="#EFEFEF", width=1)

    # El Galicia no dice de qué banco es la cuenta destino ni el concepto.
    d.text((55, 590), "Origen", fill="#7A7A7A", font=fnt("arial", 24))
    d.campo("nombre_emisor", (55, 630), dat["nombre_emi"], fill="#2A2A2A", font=fnt("arial_bold", 28))
    d.text((55, 675), "Cuenta Corriente / Caja de Ahorros",
           fill="#2A2A2A", font=fnt("arial", 22))
    d.line([(55, 740), (W - 55, 740)], fill="#EFEFEF", width=1)

    d.text((55, 770), "Número de transacción", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("referencia", (55, 810), referencia, fill="#2A2A2A", font=fnt("arial_bold", 26))

    d.text((55, 870), "Fecha", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo(("fecha", "hora"), (55, 910),
            f"{fmt_fecha_corta(dat['dt'])} a las {dat['dt'].strftime('%H:%M')} hs",
            fill="#2A2A2A", font=fnt("arial", 24))

    d.text((55, 970), "Canal", fill="#7A7A7A", font=fnt("arial", 22))
    d.text((55, 1010), "App Galicia", fill="#2A2A2A", font=fnt("arial", 24))

    finalizar(img, ruta)
    return str(ruta), _gt("Banco Galicia", dat, d, referencia=referencia)


# ---------------------------------------------------------------------------
# BBVA FRANCÉS
# ---------------------------------------------------------------------------
def comp_bbva_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"bbva_saliente_{uid}.jpg"
    dat = _datos_comunes("BBVA Francés")
    referencia = str(random.randint(10**7, 10**8 - 1))

    W, H = 820, 1380
    img, d = lienzo_nuevo(W, H, "white")

    d.logo(logo_bbva, 55, 55)
    d.campo("tipo_operacion", (55, 135), "Comprobante de transferencia",
            fill="#072146", font=fnt("arial_bold", 30))
    d.line([(55, 195), (W - 55, 195)], fill="#072146", width=2)

    # Card monto — la única plantilla que escribe la moneda con todas las letras
    d.rectangle([55, 230, W - 55, 360], fill="#F4F6F9")
    d.text((80, 255), "Monto de la operación", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo(("monto", "moneda"), (80, 300),
            f"$ {fmt_monto_ar(dat['monto'])} ARS",
            fill="#072146", font=fnt("arial_bold", 32))

    d.text((55, 395), "Cuenta de origen", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("nombre_emisor", (55, 430), dat["nombre_emi"], fill="#2A2A2A", font=fnt("arial_bold", 24))
    d.text((55, 470), "Caja de ahorros en pesos", fill="#7A7A7A", font=fnt("arial", 22))
    d.line([(55, 525), (W - 55, 525)], fill="#EEEEEE", width=1)

    d.text((55, 555), "Cuenta de destino", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("nombre_receptor", (55, 590), dat["nombre_rec"], fill="#2A2A2A", font=fnt("arial_bold", 24))
    d.campo("cbu_cvu_receptor", (55, 630), f"CBU: {dat['cbu_rec']}", fill="#2A2A2A", font=fnt("arial", 22))
    d.campo("cuit_receptor", (55, 670), f"CUIT/CUIL: {dat['cuit_rec']}", fill="#7A7A7A", font=fnt("arial", 22))
    d.line([(55, 725), (W - 55, 725)], fill="#EEEEEE", width=1)

    d.text((55, 755), "Fecha y hora de ejecución", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo(("fecha", "hora"), (55, 790),
            f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} hs",
            fill="#2A2A2A", font=fnt("arial", 24))

    d.text((55, 855), "Número de referencia / operación", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("referencia", (55, 890), referencia, fill="#2A2A2A", font=fnt("arial_bold", 24))

    d.text((55, 955), "Concepto", fill="#7A7A7A", font=fnt("arial", 22))
    d.campo("concepto", (55, 990), dat["concepto"], fill="#2A2A2A", font=fnt("arial", 24))

    d.text((55, 1180), "Este documento sirve como constancia oficial de la operación efectuada.",
           fill="#9E9E9E", font=fnt("arial", 18))
    d.text((55, 1210), "BBVA Argentina S.A.", fill="#9E9E9E", font=fnt("arial", 18))

    finalizar(img, ruta)
    return str(ruta), _gt("BBVA Francés", dat, d, referencia=referencia)


# ---------------------------------------------------------------------------
# BANCO NACIÓN (BNA+)
# ---------------------------------------------------------------------------
def comp_nacion_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"nacion_saliente_{uid}.jpg"
    dat = _datos_comunes("Banco Nación")
    referencia = f"{random.randint(0, 99999999):08d}"

    W, H = 820, 1400
    img, d = lienzo_nuevo(W, H, "white")

    # Header celeste con "Transferencia"
    d.rectangle([0, 0, W, 130], fill="#3FA9F5")
    d.polygon([(40, 65), (75, 50), (75, 80)], fill="white")  # flecha back
    d.campo("tipo_operacion", (W//2 - 110, 50), "Transferencia",
            fill="white", font=fnt("arial_bold", 32))

    d.logo(logo_nacion, W//2 - 90, 200)

    # El BNA escribe en mayúsculas, y eso se conserva: la etiqueta se compara
    # plegando mayúsculas. Lo que NO se conserva es el `.replace("Banco ", "")`
    # que tenía antes: dibujaba `GALICIA` contra una etiqueta `Banco Galicia`,
    # o sea le pedía al modelo escribir una palabra que no está en la imagen.
    y = 350
    items = [
        ("Destinatario", dat["nombre_rec"].upper(), "nombre_receptor"),
        ("CUIT", dat["cuit_rec"].replace("-", ""), "cuit_receptor"),
        ("Monto", f"${fmt_monto_ar(dat['monto'])}", ("monto", "moneda")),
        ("CBU", dat["cbu_rec"], "cbu_cvu_receptor"),
        ("Banco", dat["banco_rec"].upper(), "banco_receptor"),
        ("Motivo", dat["concepto"], "concepto"),
        ("Número de transacción", referencia, "referencia"),
        ("Fecha", f"{fmt_fecha_corta(dat['dt'])} {dat['dt'].strftime('%H:%M:%S')}",
         ("fecha", "hora")),
    ]
    for k, v, c in items:
        d.text((55, y), k, fill="#2A2A2A", font=fnt("arial_bold", 24))
        d.campo(c, (55, y + 36), v, fill="#5E5E5E", font=fnt("arial", 22))
        d.line([(55, y + 86), (W - 55, y + 86)], fill="#EEEEEE", width=1)
        y += 100

    finalizar(img, ruta)
    return str(ruta), _gt("Banco Nación", dat, d, referencia=referencia)


# ---------------------------------------------------------------------------
# NARANJA X
# ---------------------------------------------------------------------------
def comp_naranjax_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"naranjax_saliente_{uid}.jpg"
    dat = _datos_comunes("Naranja X")
    # Antes era un `uuid4`: ningún banco emite eso, y el modelo aprendía como
    # válido un formato de referencia que no existe en la realidad.
    referencia = str(random.randint(10**11, 10**12 - 1))
    coelsa = gen_coelsa()

    W, H = 820, 1600
    img, d = lienzo_nuevo(W, H, "white")

    d.logo(logo_naranjax, 55, 50)
    d.campo("tipo_operacion", (55, 130), "Comprobante de transferencia",
            fill="#1A1A1A", font=fnt("arial_bold", 30))

    # Card "Enviaste" — los centavos van aparte y en chico, como en la app
    d.rounded_rectangle([55, 200, W - 55, 360], radius=24,
                        outline="#E5E5E5", width=1, fill="white")
    d.text((85, 225), "Enviaste", fill="#1A1A1A", font=fnt("arial_bold", 28))
    monto_str = fmt_monto_ar(dat['monto'])
    parte_entera, decimales = monto_str.split(",")
    d.campo(("monto", "moneda"), (85, 270), f"$ {parte_entera}",
            fill="#1A1A1A", font=fnt("arial_bold", 50),
            leido=f"$ {monto_str}")
    ancho_ent = d.textlength(f"$ {parte_entera}", font=fnt("arial_bold", 50))
    d.text((85 + ancho_ent + 4, 275), decimales,
           fill="#1A1A1A", font=fnt("arial_bold", 28))
    d.campo(("fecha", "hora"), (85, 330),
            f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} h",
            fill="#7A7A7A", font=fnt("arial", 20))

    # Card origen
    d.rounded_rectangle([55, 400, W - 55, 660], radius=24,
                        outline="#E5E5E5", width=1, fill="white")
    d.text((85, 425), "Cuenta origen", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.rectangle([85, 470, 125, 510], outline="#F25A22", width=2)
    d.text((92, 477), "NX", fill="#F25A22", font=fnt("arial_bold", 18))
    d.campo("nombre_emisor", (140, 470), dat["nombre_emi"], fill="#1A1A1A", font=fnt("arial_bold", 22))
    d.campo("banco_emisor", (140, 500), "Naranja X", fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 540), "CBU", fill="#7A7A7A", font=fnt("arial", 20))
    d.campo("cbu_cvu_emisor", (85, 565), dat["cbu_emi"], fill="#1A1A1A", font=fnt("arial", 22))
    d.text((85, 605), "CUIL", fill="#7A7A7A", font=fnt("arial", 20))
    d.campo("cuit_emisor", (85, 630), dat["cuit_emi"], fill="#1A1A1A", font=fnt("arial", 22))

    # Card destino
    d.rounded_rectangle([55, 700, W - 55, 960], radius=24,
                        outline="#E5E5E5", width=1, fill="white")
    d.text((85, 725), "Cuenta destino", fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.campo("nombre_receptor", (140, 770), dat["nombre_rec"], fill="#1A1A1A", font=fnt("arial_bold", 22))
    d.campo("banco_receptor", (140, 800), dat["banco_rec"], fill="#7A7A7A", font=fnt("arial", 20))
    d.text((85, 840), "CBU", fill="#7A7A7A", font=fnt("arial", 20))
    d.campo("cbu_cvu_receptor", (85, 865), dat["cbu_rec"], fill="#1A1A1A", font=fnt("arial", 22))
    d.text((85, 905), "CUIL", fill="#7A7A7A", font=fnt("arial", 20))
    d.campo("cuit_receptor", (85, 930), dat["cuit_rec"], fill="#1A1A1A", font=fnt("arial", 22))

    # Card operación — Naranja X no muestra el concepto
    d.rounded_rectangle([55, 1000, W - 55, 1270], radius=24,
                        outline="#E5E5E5", width=1, fill="white")
    d.text((85, 1025), "Información de la operación",
           fill="#1A1A1A", font=fnt("arial_bold", 24))
    d.text((85, 1075), "COELSA ID", fill="#7A7A7A", font=fnt("arial", 20))
    d.campo("coelsa_id", (85, 1105), coelsa, fill="#1A1A1A", font=fnt("arial_bold", 22))
    d.text((85, 1160), "Código de transacción",
           fill="#7A7A7A", font=fnt("arial", 20))
    d.campo("referencia", (85, 1190), referencia, fill="#1A1A1A", font=fnt("arial", 22))

    d.text((55, 1320),
           "Naranja Digital Compañía Financiera S.A.U es una entidad financiera",
           fill="#9E9E9E", font=fnt("arial", 16))
    d.text((55, 1345),
           "autorizada por el Banco Central de la República Argentina.",
           fill="#9E9E9E", font=fnt("arial", 16))

    finalizar(img, ruta)
    return str(ruta), _gt("Naranja X", dat, d,
                          referencia=referencia, coelsa_id=coelsa)


# ---------------------------------------------------------------------------
# BRUBANK
# ---------------------------------------------------------------------------
def comp_brubank_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"brubank_saliente_{uid}.jpg"
    dat = _datos_comunes("Brubank")
    referencia = str(random.randint(10**9, 10**10 - 1))

    W, H = 820, 1340
    img, d = lienzo_nuevo(W, H, "white")

    # Header violeta
    d.rectangle([0, 0, W, 280], fill="#5B2D90")
    d.logo(logo_brubank, 55, 55)
    d.campo("tipo_operacion", (55, 130), "Transferencia enviada",
            fill="white", font=fnt("arial_bold", 26))
    d.campo(("monto", "moneda"), (55, 175), f"$ {fmt_monto_ar(dat['monto'])}",
            fill="white", font=fnt("arial_bold", 50))

    y = 330
    items = [
        ("Para", dat["nombre_rec"], "nombre_receptor"),
        ("CUIT/CUIL", dat["cuit_rec"], "cuit_receptor"),
        ("Banco", dat["banco_rec"], "banco_receptor"),
        ("CBU", dat["cbu_rec"], "cbu_cvu_receptor"),
        ("Motivo", dat["concepto"], "concepto"),
        ("Fecha", f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} hs",
         ("fecha", "hora")),
        ("Número de operación", referencia, "referencia"),
    ]
    for k, v, c in items:
        d.text((55, y), k, fill="#7A7A7A", font=fnt("arial", 22))
        d.campo(c, (55, y + 32), v, fill="#1A1A1A", font=fnt("arial_bold", 24))
        d.line([(55, y + 80), (W - 55, y + 80)], fill="#EEEEEE", width=1)
        y += 96

    finalizar(img, ruta)
    return str(ruta), _gt("Brubank", dat, d, referencia=referencia)


# ---------------------------------------------------------------------------
# UALÁ
# ---------------------------------------------------------------------------
def comp_uala_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"uala_saliente_{uid}.jpg"
    dat = _datos_comunes("Ualá")
    referencia = str(random.randint(10**9, 10**10 - 1))

    W, H = 820, 1280
    img, d = lienzo_nuevo(W, H, "#F5F8FA")

    d.logo(logo_uala, 55, 55)
    d.campo("tipo_operacion", (55, 145), "Transferiste",
            fill="#5E5E5E", font=fnt("arial", 24))
    d.campo(("monto", "moneda"), (55, 185), f"$ {fmt_monto_ar(dat['monto'])}",
            fill="#1A1A1A", font=fnt("arial_bold", 58))
    d.campo("nombre_receptor", (55, 270), f"a {dat['nombre_rec']}",
            fill="#1A1A1A", font=fnt("arial_bold", 28))

    d.rounded_rectangle([40, 340, W - 40, 920], radius=20,
                        outline="#DCE4EA", width=1, fill="white")
    y = 370
    items = [
        ("Cuenta destino", dat["banco_rec"], "banco_receptor"),
        ("CBU", dat["cbu_rec"], "cbu_cvu_receptor"),
        ("CUIT/CUIL", dat["cuit_rec"], "cuit_receptor"),
        ("Motivo", dat["concepto"], "concepto"),
        ("Fecha y hora", f"{fmt_fecha_corta(dat['dt'])} {dat['dt'].strftime('%H:%M')} hs",
         ("fecha", "hora")),
        ("Comprobante N°", referencia, "referencia"),
    ]
    for k, v, c in items:
        d.text((75, y), k, fill="#7A7A7A", font=fnt("arial", 20))
        d.campo(c, (75, y + 30), v, fill="#1A1A1A", font=fnt("arial_bold", 22))
        d.line([(75, y + 76), (W - 75, y + 76)], fill="#EEF2F5", width=1)
        y += 90

    finalizar(img, ruta)
    return str(ruta), _gt("Ualá", dat, d, referencia=referencia)


# ---------------------------------------------------------------------------
# PERSONAL PAY
# ---------------------------------------------------------------------------
def comp_personalpay_saliente() -> Tuple[str, dict]:
    uid = str(uuid.uuid4())[:8]
    ruta = OUT_DIR / f"personalpay_saliente_{uid}.jpg"
    dat = _datos_comunes("Personal Pay")
    referencia = str(random.randint(10**9, 10**10 - 1))

    W, H = 820, 1300
    img, d = lienzo_nuevo(W, H, "white")

    # Header violeta degradé simple — el logo va escrito, no dibujado aparte
    d.rectangle([0, 0, W, 240], fill="#7B2D9F")
    d.visible("banco_emisor")
    d.text((55, 55), "personal", fill="white", font=fnt("arial_bold", 32))
    d.text((205, 55), "pay", fill="#FFE066", font=fnt("arial_bold", 32))
    d.campo("tipo_operacion", (55, 130), "Enviaste", fill="white", font=fnt("arial", 24))
    d.campo(("monto", "moneda"), (55, 165), f"$ {fmt_monto_ar(dat['monto'])}",
            fill="white", font=fnt("arial_bold", 46))

    y = 290
    items = [
        ("Destinatario", dat["nombre_rec"], "nombre_receptor"),
        ("Banco", dat["banco_rec"], "banco_receptor"),
        ("CBU/CVU", dat["cbu_rec"], "cbu_cvu_receptor"),
        ("CUIT/CUIL", dat["cuit_rec"], "cuit_receptor"),
        ("Concepto", dat["concepto"], "concepto"),
        ("Fecha", f"{fmt_fecha_corta(dat['dt'])} - {dat['dt'].strftime('%H:%M')} hs",
         ("fecha", "hora")),
        ("N° de operación", referencia, "referencia"),
    ]
    for k, v, c in items:
        d.text((55, y), k, fill="#7A7A7A", font=fnt("arial", 22))
        d.campo(c, (55, y + 32), v, fill="#1A1A1A", font=fnt("arial_bold", 24))
        d.line([(55, y + 80), (W - 55, y + 80)], fill="#EEEEEE", width=1)
        y += 96

    finalizar(img, ruta)
    return str(ruta), _gt("Personal Pay", dat, d, referencia=referencia)


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

# Todos los bancos por igual, decidido el 2026-08-11.
#
# Hasta acá esto copiaba la proporción de los 51 comprobantes reales, medida
# sobre la base el 2026-08-07: Mercado Pago 25 (49%) · Macro 8 · Galicia 6 ·
# Santander 5 · Nación 2 · Naranja X 2 · Brubank 1 · y CERO de BBVA, Ualá y
# Personal Pay. El resultado era que tres bancos quedaban con 11 ejemplos en
# 600, que no alcanza para aprender una maqueta — y la medición de F10 ya venía
# diciendo que el modelo es un especialista en Mercado Pago y mediocre en el
# resto, que es exactamente lo que esa proporción enseña.
#
# El ejemplo número 200 de Mercado Pago casi no agrega; el número 40 de BBVA sí.
# Parte del sesgo real vuelve solo: los comprobantes reales que `reales.py` le
# suma al dataset siguen siendo mayormente Mercado Pago.


# ===========================================================================
# EL DATASET
# ===========================================================================
def verificar(gt: dict) -> None:
    """Que la etiqueta esté canónica. Es el chequeo que faltó la vez pasada.

    El intento anterior entrenó con montos en formato argentino y CUIT con
    guiones sin que nada se quejara: el error recién se habría visto en el
    número final de F10, ya sin forma de saber de dónde salía.
    """
    assert list(gt) == CAMPOS, f"claves fuera de orden: {list(gt)}"
    assert re.fullmatch(r"\d+\.\d{2}", gt["monto"]), f"monto {gt['monto']!r}"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", gt["fecha"]), f"fecha {gt['fecha']!r}"
    assert gt["moneda"] == "ARS", f"moneda {gt['moneda']!r}"

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


def ejemplo(plantilla, perfil: str = NITIDO) -> dict:
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
    global _perfil
    _perfil = perfil
    ruta, gt = plantilla()
    verificar(gt)
    return {
        "images": [ruta],
        "messages": [
            {"role": "user", "content": PROMPT},
            {"role": "assistant", "content": json.dumps(gt, ensure_ascii=False)},
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Genera el dataset sintético de F8.")
    p.add_argument("--n", type=int, default=4,
                   help="ejemplos totales, en partes iguales entre los 10 bancos")
    p.add_argument("--degradados", type=float, default=0.5,
                   help="fracción con calidad de foto reenviada (0.5 = mitad y mitad)")
    p.add_argument("--semilla", type=int, default=42)
    p.add_argument("--salida", type=Path, default=SALIDA_DIR / "train.jsonl")
    args = p.parse_args()

    random.seed(args.semilla)
    Faker.seed(args.semilla)

    # La bolsa repite cada banco según su peso, y después se recorre en orden:
    # así la proporción sale exacta y no librada al azar de 300 tiradas.
    bolsa = list(TEMPLATES.values())

    # El perfil se reparte por posición y no al azar, para que la proporción
    # salga exacta y quede pareja entre los bancos: si se sorteara, un banco de
    # peso 1 podría quedar entero de un solo lado.
    corte = round(args.n * args.degradados)
    perfiles = [DEGRADADO] * corte + [NITIDO] * (args.n - corte)
    registros = [ejemplo(bolsa[i % len(bolsa)], perfiles[i]) for i in range(args.n)]
    random.shuffle(registros)

    args.salida.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in registros),
        encoding="utf-8",
    )
    print(f"{len(registros)} ejemplos → {args.salida}")
    print(f"imágenes → {OUT_DIR}")


if __name__ == "__main__":
    main()

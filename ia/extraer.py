"""Extrae los 16 campos de un comprobante bancario con Qwen2-VL, local.

    ia/.venv/bin/python ia/extraer.py ia/comprobantes/001.jpeg

Imprime una línea de JSON por imagen. El modelo corre en esta máquina:
ninguna imagen ni ningún campo sale de acá.

API verificada contra mlx-vlm 0.1.15 instalado, no contra la documentación:
en esta versión `generate()` devuelve un str, no un objeto con .text.
"""

import argparse
import contextlib
import json
import sys
from pathlib import Path

MODELO = "mlx-community/Qwen2-VL-7B-Instruct-4bit"

# Los 16 campos, en el mismo orden que la tabla `comprobante` de web/migraciones.
CAMPOS = [
    "tipo_operacion", "monto", "moneda", "fecha", "hora",
    "nombre_emisor", "cuit_emisor", "cbu_cvu_emisor", "banco_emisor",
    "nombre_receptor", "cuit_receptor", "cbu_cvu_receptor", "banco_receptor",
    "concepto", "referencia", "coelsa_id",
]

# v1: el prompt del intento anterior. Se conserva para poder reproducir la
# primera medición, que quedó en ia/salida_cruda.jsonl.
PROMPT_V1 = (
    "Eres un sistema de procesamiento bancario experto. Analizá la imagen del "
    "comprobante y extraé en JSON estricto los siguientes campos: "
    + ", ".join(CAMPOS)
    + ". La fecha en formato YYYY-MM-DD y la hora en HH:MM. Usá null donde el "
    "campo no esté presente. No incluyas texto adicional ni markdown."
)

# v2: escrito contra los tres errores que se midieron en la corrida de v1 sobre
# los 52 comprobantes reales — no son fallas de lectura, son de consigna:
#   1. metía el número de operación del banco dentro de coelsa_id
#      (5 valores idénticos a `referencia`, 13 de 18 chars alfanuméricos)
#   2. escribía "N/A" en vez de null (4 casos)
#   3. devolvía la fecha en DD/MM/YYYY pese a pedirla ISO (8 de 49), y el monto
#      como texto en la mitad de los casos
PROMPT_V2 = """Sos un sistema experto en comprobantes bancarios argentinos. Leé la imagen y devolvé UN objeto JSON con exactamente estas 16 claves:

tipo_operacion   qué operación es: "transferencia", "pago", "deposito", "extraccion"
monto            SOLO el número, punto decimal, sin símbolo ni separador de miles: 15000.50
moneda           "ARS" o "USD"
fecha            estrictamente YYYY-MM-DD. Convertí si el comprobante la muestra distinto
hora             estrictamente HH:MM en 24 horas
nombre_emisor    quién ENVÍA el dinero
cuit_emisor      CUIT/CUIL del que envía: exactamente 11 dígitos, sin guiones ni puntos
cbu_cvu_emisor   CBU o CVU del que envía: exactamente 22 dígitos
banco_emisor     banco o billetera del que envía
nombre_receptor  quién RECIBE el dinero
cuit_receptor    CUIT/CUIL del que recibe: exactamente 11 dígitos, sin guiones ni puntos
cbu_cvu_receptor CBU o CVU del que recibe: exactamente 22 dígitos
banco_receptor   banco o billetera del que recibe
concepto         motivo o descripción de la operación
referencia       el número de operación, comprobante o ticket que muestra el banco
coelsa_id        SOLO el identificador COELSA de la cámara compensadora: 22 caracteres alfanuméricos en MAYÚSCULA

REGLAS QUE NO SE NEGOCIAN:
- coelsa_id y referencia son DISTINTOS. El número de operación del banco va en `referencia`, NUNCA en `coelsa_id`. Si no ves un identificador de 22 caracteres alfanuméricos, coelsa_id es null.
- Si un dato no está en la imagen, el valor es null (el literal JSON, sin comillas). Nunca "N/A", nunca "-", nunca "no disponible", nunca inventar.
- No completes un dato por deducción. Solo lo que se lee en la imagen.
- Un CUIT tiene 11 dígitos y un CBU tiene 22. Si el número que ves tiene 22 dígitos es un CBU, no un CUIT.
- Respondé únicamente el JSON. Sin markdown, sin explicaciones, sin ```."""

# v3: v2 arregló el monto (26/50 → 44/44 bien formados) pero rompió otra cosa:
# 8 de 52 comprobantes no parsearon. Todos con la misma firma — envueltos en
# markdown, 1 llave abierta y 0 cerradas, más largos que la mediana. Se cortaron
# por max_tokens. El prompt largo de v2 inducía respuestas largas.
# v3 conserva las reglas de formato de v2 y recorta todo lo demás.
PROMPT_V3 = """Extraé los datos de este comprobante bancario argentino y devolvé SOLO un objeto JSON, sin markdown y sin explicaciones.

Claves exactas, en este orden:
tipo_operacion, monto, moneda, fecha, hora, nombre_emisor, cuit_emisor, cbu_cvu_emisor, banco_emisor, nombre_receptor, cuit_receptor, cbu_cvu_receptor, banco_receptor, concepto, referencia, coelsa_id

Formato:
- monto: número, punto decimal, sin símbolos ni separador de miles → 15000.50
- moneda: "ARS" o "USD"
- fecha: YYYY-MM-DD · hora: HH:MM
- cuit: 11 dígitos, sin guiones · cbu_cvu: 22 dígitos
- coelsa_id: 22 caracteres alfanuméricos. El número de operación del banco NO es el COELSA: ese va en referencia.
- emisor = quien envía · receptor = quien recibe

Si un dato no está en la imagen, poné null. Nunca "N/A", nunca lo deduzcas.
Valores cortos, sin comentarios."""

# v4: escrito después de mirar tres comprobantes reales (001 Macro, 003 BNA+,
# 004 Santander). Corrige un error propio de v3 y agrega lo que se vio:
#
#   · En el Macro el "N° de operación" y el "ID COELSA" son EL MISMO valor de 22
#     caracteres. v3 decía "el número de operación NO es el COELSA" y así le
#     enseñó a descartar el valor correcto: bajó de 4/52 a 1/52. Se saca.
#   · Ningún identificador está en todos los comprobantes: el Macro no muestra
#     CBU (solo 4 dígitos de cuenta), el Santander no muestra CUIT. Lo único
#     presente en los tres es el nombre del titular.
#   · Hay comprobantes en dólares (Santander, "U$S 100,00"). La moneda decide si
#     un movimiento del extracto es siquiera candidato.
#   · Los montos vienen en formato argentino: $ 250.000 · $81.687,80 · U$S 100,00
PROMPT_V4 = """Extraé los datos de este comprobante bancario argentino y devolvé SOLO un objeto JSON, sin markdown y sin explicaciones.

Claves exactas, en este orden:
tipo_operacion, monto, moneda, fecha, hora, nombre_emisor, cuit_emisor, cbu_cvu_emisor, banco_emisor, nombre_receptor, cuit_receptor, cbu_cvu_receptor, banco_receptor, concepto, referencia, coelsa_id

Formato:
- monto: número con punto decimal, sin símbolos ni separador de miles. "$ 250.000" → 250000.00 · "$81.687,80" → 81687.80 · "U$S 100,00" → 100.00
- moneda: "ARS" para $ o pesos · "USD" para U$S, US$ o dólares. Miralo bien: cambia el significado del monto
- fecha: YYYY-MM-DD, convertí desde DD/MM/AAAA · hora: HH:MM (si el comprobante no muestra hora, null)
- cuit: 11 dígitos seguidos, sin guiones ni puntos
- cbu_cvu: 22 dígitos. Puede aparecer como "CBU" o como "Cuenta destino". Si el comprobante solo muestra los últimos dígitos de la cuenta (por ejemplo "CA $ 7192"), eso NO es un CBU: poné null
- coelsa_id: 22 caracteres alfanuméricos en mayúscula. Suele estar rotulado "ID COELSA". En algunos bancos el "N° de operación" es ese mismo valor: si mide 22 caracteres alfanuméricos, ponelo en los dos campos
- referencia: el número de operación, comprobante o ticket, tal como lo muestra
- receptor = a quien le llega la plata ("Para", "Destinatario", "Titular cuenta destino")
- emisor = de dónde sale ("Desde", "Cuenta débito")

Si un dato no está en la imagen, poné null. Nunca "N/A", nunca lo deduzcas.
No todos los comprobantes traen todos los campos: es normal que varios queden en null."""

PROMPTS = {"v1": PROMPT_V1, "v2": PROMPT_V2, "v3": PROMPT_V3, "v4": PROMPT_V4}


def parchear_detokenizador():
    """Evita que una tilde tumbe la corrida entera.

    `BPEStreamingDetokenizer.add_token` (mlx-vlm 0.1.15, tokenizer_utils.py:189)
    acumula tokens y recién descarga cuando llega uno que empieza con espacio.
    Si ese corte cae en medio de un carácter multibyte —cualquier tilde, ñ o ¡ del
    español— hace `.decode("utf-8")` sin tolerancia y tira UnicodeDecodeError, que
    se propaga y mata la generación completa. Visto en vivo: byte `0xa1`, el
    segundo de "¡".

    Las 4 corridas v1-v4 (204 extracciones) nunca lo dispararon, así que es raro;
    pero cuando pasa se pierde la corrida entera de 51 comprobantes, no una imagen.

    Se reemplazan los dos métodos por copias idénticas salvo `errors="replace"`.
    El costo es que un carácter partido queda como U+FFFD en vez de leerse bien:
    ese campo va a fallar la validación, que es el resultado honesto. Lo correcto
    de verdad sería un decodificador incremental que retenga la secuencia
    incompleta, pero eso cambia el modelo de acumulación de la librería.
    """
    from mlx_vlm.tokenizer_utils import BPEStreamingDetokenizer as D
    from mlx_vlm.tokenizer_utils import _remove_space

    def add_token(self, token):
        v = self.tokenmap[token]
        if self._byte_decoder[v[0]] == 32:
            current_text = bytearray(
                self._byte_decoder[c] for c in self._unflushed
            ).decode("utf-8", errors="replace")
            if self.text or not self.trim_space:
                self.text += current_text
            else:
                self.text += _remove_space(current_text)
            self._unflushed = v
        else:
            self._unflushed += v

    def finalize(self):
        current_text = bytearray(
            self._byte_decoder[c] for c in self._unflushed
        ).decode("utf-8", errors="replace")
        if self.text or not self.trim_space:
            self.text += current_text
        else:
            self.text += _remove_space(current_text)
        self._unflushed = ""

    D.add_token, D.finalize = add_token, finalize


def parsear(salida):
    """El JSON del modelo, o el texto crudo si no se pudo rescatar nada.

    Devuelve (dict, None) si salió bien, (None, texto_crudo) si no.

    Tolera dos cosas que el modelo hace pese a que el prompt las prohíbe:
    envolver la respuesta en markdown, y quedarse sin tokens a mitad del JSON.
    Un JSON cortado igual trae bien los campos que alcanzó a escribir, y
    tirarlo entero desperdicia lo que sí leyó: se rescatan los pares completos
    y el resto queda en null, que es lo que después manda a carga manual.
    """
    texto = salida.strip()
    if "```" in texto:                               # a veces envuelve en markdown
        partes = texto.split("```")
        texto = partes[1] if len(partes) > 1 else texto
        if texto.lstrip().startswith("json"):
            texto = texto.lstrip()[4:]
        texto = texto.strip()

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        datos = None

    # json.loads devuelve CUALQUIER tipo JSON, no solo objetos: `5`, `"texto"`,
    # `[1,2]`, `null` parsean sin error y después `datos.get(...)` revienta con
    # "'int' object has no attribute 'get'". Un modelo colapsado emite exactamente
    # eso, y una sola imagen así tumbaba la corrida entera de 51 comprobantes.
    # `rescatar()` ya se protegía con isinstance; en este camino faltaba.
    if not isinstance(datos, dict):
        datos = rescatar(texto)
        if datos is None:
            return None, salida
    return {campo: datos.get(campo) for campo in CAMPOS}, None


def rescatar(texto):
    """Los pares "clave": valor completos de un JSON truncado, o None."""
    if "{" not in texto:
        return None
    # se cierra el objeto en el último par que quedó entero
    cuerpo = texto[texto.index("{") + 1:]
    corte = max(cuerpo.rfind(","), cuerpo.rfind("}"))
    if corte <= 0:
        return None
    try:
        datos = json.loads("{" + cuerpo[:corte] + "}")
    except json.JSONDecodeError:
        return None
    return datos if isinstance(datos, dict) and datos else None


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("imagenes", nargs="+", help="rutas a los comprobantes")
    p.add_argument("--prompt", choices=PROMPTS, default="v3")
    p.add_argument("--max-tokens", type=int, default=1000)
    p.add_argument("--adaptador", type=Path, default=None, metavar="DIR",
                   help="directorio del LoRA entrenado, p.ej. ia/checkpoints/lora_v1. "
                        "Sin esto corre el modelo base (zero-shot)")
    p.add_argument("--resize", type=int, nargs=2, default=None, metavar=("ANCHO", "ALTO"),
                   help="redimensionar las imágenes antes de inferir. Tiene que ser el "
                        "MISMO valor con que se entrenó el adaptador: si no, el modelo ve "
                        "imágenes de un tamaño que nunca vio entrenando")
    args = p.parse_args()

    faltantes = [i for i in args.imagenes if not Path(i).exists()]
    if faltantes:
        sys.exit(f"no existe: {faltantes[0]}")

    # Se chequea ANTES de cargar 4,4 GB de modelo: el error de mlx-vlm llega
    # recién después y esa espera no compra nada.
    if args.adaptador:
        for archivo in ("adapter_config.json", "adapters.safetensors"):
            if not (args.adaptador / archivo).exists():
                sys.exit(f"falta {args.adaptador / archivo} — "
                         f"¿terminó de entrenar? ¿es el directorio de salida?")

    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template
    from transformers import Qwen2VLImageProcessor

    que = f"{MODELO} + {args.adaptador}" if args.adaptador else f"{MODELO} (zero-shot)"
    print(f"cargando {que}...", file=sys.stderr)
    # load() con adapter_path arma las capas LoRA y les carga los pesos
    # (mlx_vlm.utils.apply_lora_layers). El adapter_config.json que escribe
    # entrenar.py trae el `rank` que esa función exige.
    #
    # El redirect NO es cosmético: con --adaptador, get_peft_model imprime
    # "#trainable params: ..." por STDOUT, que acá es el JSONL. Esa línea se coló en
    # ia/salida_lora_v2.jsonl y el importador descartó el archivo entero. Todo lo que
    # no sea un registro va a stderr.
    with contextlib.redirect_stdout(sys.stderr):
        modelo, processor = load(
            MODELO, adapter_path=str(args.adaptador) if args.adaptador else None)

    parchear_detokenizador()   # una tilde partida no puede matar la corrida

    # load() arma el image processor "fast", que solo devuelve tensores de PyTorch
    # y hace explotar a mlx_vlm con "Only returning PyTorch tensors is currently
    # supported". Verificado: sin esta línea, falla. Se reemplaza solo el
    # image_processor para conservar el detokenizer que generate() necesita.
    processor.image_processor = Qwen2VLImageProcessor.from_pretrained(
        MODELO, use_fast=False
    )

    prompt = apply_chat_template(
        processor, modelo.config, PROMPTS[args.prompt], num_images=1
    )

    for n, ruta in enumerate(args.imagenes, 1):
        print(f"[{n}/{len(args.imagenes)}] {Path(ruta).name}", file=sys.stderr, flush=True)
        # `resize_shape` viaja por **kwargs hasta prepare_inputs, igual que en el
        # CLI de mlx-vlm (mlx_vlm/generate.py:108). Se aplica porque el
        # image_processor parcheado es el de transformers y no el BaseImageProcessor
        # de mlx-vlm, que es el caso que utils.py:756 saltea.
        extra = {"resize_shape": tuple(args.resize)} if args.resize else {}
        salida = generate(
            modelo, processor, prompt, [ruta],
            max_tokens=args.max_tokens, temperature=0.0, verbose=False, **extra,
        )
        campos, crudo = parsear(salida)
        print(json.dumps(
            {"archivo": Path(ruta).name, "campos": campos, "sin_parsear": crudo},
            ensure_ascii=False,
        ))


if __name__ == "__main__":
    main()

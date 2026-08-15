"""Guarda el comprobante que sube un cliente y lo deja siempre como imagen.

El cliente puede mandar una foto o un PDF; hacia adentro sale siempre un JPEG,
porque `ia/extraer.py` (parte 2) lee imágenes. El nombre del archivo lo pone el
servidor: un nombre venido de afuera es la vía clásica para escribir fuera de la
carpeta.
"""

import subprocess
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image

CARPETA = Path(__file__).parent / "comprobantes"
EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
TAMANO_MAXIMO = 10 * 1024 * 1024  # 10 MB


class ArchivoRechazado(Exception):
    """Lo que subió el cliente no sirve. El mensaje es para mostrarle a él."""


def guardar(cliente_id: int, nombre_original: str, contenido: bytes) -> str:
    """Valida, convierte si hace falta y devuelve la ruta relativa a CARPETA."""
    extension = Path(nombre_original).suffix.lower()
    if extension not in EXTENSIONES:
        raise ArchivoRechazado("Solo se aceptan imágenes (JPG, PNG, WEBP) o un PDF.")
    if not contenido:
        raise ArchivoRechazado("El archivo llegó vacío.")
    if len(contenido) > TAMANO_MAXIMO:
        raise ArchivoRechazado("El archivo pesa más de 10 MB. Sacá la foto con menos calidad.")

    destino = CARPETA / str(cliente_id)
    destino.mkdir(parents=True, exist_ok=True)
    nombre = uuid.uuid4().hex

    if extension == ".pdf":
        archivo = _pdf_a_jpeg(contenido, destino / nombre)
    else:
        # La extensión no prueba nada: un .jpg puede traer cualquier cosa adentro.
        # Pillow abre el contenido de verdad, y así no guardamos basura que la
        # parte 2 no va a poder leer.
        if not _es_imagen(contenido):
            raise ArchivoRechazado("El archivo no se pudo abrir como imagen.")
        archivo = destino / f"{nombre}{extension}"
        archivo.write_bytes(contenido)

    return str(archivo.relative_to(CARPETA))


def _es_imagen(contenido: bytes) -> bool:
    try:
        Image.open(BytesIO(contenido)).verify()
    except Exception:  # Pillow tira de todo: OSError, SyntaxError, DecompressionBomb...
        return False
    return True


def _pdf_a_jpeg(pdf: bytes, destino_sin_extension: Path) -> Path:
    # ponytail: `pdftoppm` (poppler) ya está instalado en la máquina, así que no
    # sumamos PyMuPDF. Si el binario desaparece, el reemplazo es `pip install
    # pymupdf` y tres líneas acá adentro.
    with tempfile.NamedTemporaryFile(suffix=".pdf") as temporal:
        temporal.write(pdf)
        temporal.flush()
        try:
            subprocess.run(
                # Solo la página 1: un comprobante no tiene más.
                ["pdftoppm", "-jpeg", "-r", "200", "-f", "1", "-l", "1", "-singlefile",
                 temporal.name, str(destino_sin_extension)],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            raise ArchivoRechazado(
                "No se puede convertir PDF en este servidor. Subí una foto."
            ) from None
        except subprocess.CalledProcessError:
            raise ArchivoRechazado("El PDF está dañado o no se pudo leer.") from None

    convertido = destino_sin_extension.with_suffix(".jpg")
    if not convertido.exists():
        raise ArchivoRechazado("El PDF no tenía ninguna página que se pueda leer.")
    return convertido

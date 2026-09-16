"""download.py
Descarga el audio de un video de YouTube usando yt-dlp.
"""

import re
import subprocess
from pathlib import Path

from src.util.ffmpeg import get_ffmpeg_dir

# Regex para extraer el video_id de una URL de YouTube (v=, youtu.be/ o shorts/)
_VIDEO_ID_RE = r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})"


def extract_video_id(url: str) -> str:
    """Extrae el video_id (11 caracteres) de una URL de YouTube."""
    match = re.search(_VIDEO_ID_RE, url)
    if not match:
        raise ValueError(f"No pude extraer el video_id de la URL: {url}")
    return match.group(1)


def fetch_title(url: str) -> str:
    """Consulta el título del video llamando a yt-dlp (solo metadata).

    Devuelve el título o "" si no se pudo obtener o salió vacío.
    """
    cmd = ["yt-dlp", "--print", "%(title)s", url]
    print(f"  Obteniendo título -> {url}")
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0 or not resultado.stdout.strip():
        print(f"      ! No se pudo obtener el título: {resultado.stderr.strip()[:120]}")
        return ""
    return resultado.stdout.strip()


def sanitize_title(title: str) -> str:
    """Limpia el título para usarlo como nombre de archivo.

    Quita caracteres inválidos en sistemas de archivos, colapsa espacios y
    recorta a ~80 caracteres. Devuelve "video" si queda vacío.
    """
    limpio = re.sub(r'[\\/:*?"<>|]', "", title)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    limpio = limpio[:80].rstrip(" .")
    return limpio or "video"


def download_audio(url: str, dest_wav: Path) -> Path:
    """Descarga solo el audio del video como WAV en dest_wav y devuelve su ruta.

    Si yt-dlp nombra el archivo distinto a lo esperado, se busca un *.wav en la
    carpeta y se renombra al nombre final.
    """
    print(f"Descargando audio con yt-dlp -> {dest_wav}")
    dest_wav.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        "-x", "--audio-format", "wav",
        "-o", str(dest_wav.with_suffix("")) + ".%(ext)s",
        url,
    ]
    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir:
        cmd += ["--ffmpeg-location", ffmpeg_dir]
    print("  Comando:", " ".join(cmd))

    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"yt-dlp falló:\n{resultado.stderr}")

    if not dest_wav.exists():
        # yt-dlp a veces nombra distinto; buscar el .wav generado en la carpeta
        candidatos = list(dest_wav.parent.glob("*.wav"))
        if not candidatos:
            raise RuntimeError("No se encontró el archivo .wav descargado.")
        candidatos[0].rename(dest_wav)

    return dest_wav
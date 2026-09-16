"""ffmpeg.py
Utilidades para localizar los binarios de ffmpeg/ffprobe del sistema.
"""

import shutil
from pathlib import Path


def get_ffmpeg_dir() -> str | None:
    """Devuelve el directorio que contiene los binarios ffmpeg/ffprobe.

    Prioriza los binarios estáticos del venv (paquete static-ffmpeg) si están
    disponibles; si no, devuelve None para que se use el ffmpeg de sistema.
    """
    try:
        from static_ffmpeg import add_paths

        add_paths(weak=True)
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return str(Path(ffmpeg).parent)
    except ImportError:
        pass
    return None
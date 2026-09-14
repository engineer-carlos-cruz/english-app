#!/usr/bin/env python3
"""
_test.py
--------
Prueba inicial del pipeline: solo descargar el audio de un video de YouTube
con yt-dlp y guardarlo como WAV.

USO:
    python _test.py "https://www.youtube.com/watch?v=XXXXXXXX"
"""

import argparse
import re
import shutil
import subprocess
from pathlib import Path


def extraer_video_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if not match:
        raise ValueError(f"No pude extraer el video_id de la URL: {url}")
    return match.group(1)


def ruta_ffmpeg() -> str:
    """Devuelve la carpeta con ffmpeg/ffprobe estáticos del venv (vía static-ffmpeg),
    o None para usar los de sistema."""
    try:
        from static_ffmpeg import add_paths
        add_paths(weak=True)
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return str(Path(ffmpeg).parent)
    except ImportError:
        pass
    return None


def descargar_audio(url: str, destino_wav: Path) -> None:
    print(f"Descargando audio con yt-dlp -> {destino_wav}")
    destino_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "-x", "--audio-format", "wav",
        "-o", str(destino_wav.with_suffix("")) + ".%(ext)s",
        url,
    ]
    ffmpeg_dir = ruta_ffmpeg()
    if ffmpeg_dir:
        cmd += ["--ffmpeg-location", ffmpeg_dir]
    print("  Comando:", " ".join(cmd))
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"yt-dlp falló:\n{resultado.stderr}")

    if not destino_wav.exists():
        candidatos = list(destino_wav.parent.glob("*.wav"))
        if not candidatos:
            raise RuntimeError("No se encontró el archivo .wav descargado.")
        candidatos[0].rename(destino_wav)


def main():
    parser = argparse.ArgumentParser(description="Descarga el audio de un video de YouTube")
    parser.add_argument("url", help="URL del video de YouTube")
    parser.add_argument("--salida", default="output", help="Carpeta base de salida (default: output)")
    args = parser.parse_args()

    video_id = extraer_video_id(args.url)
    carpeta_video = Path(args.salida) / video_id
    audio_path = carpeta_video / "video.wav"

    descargar_audio(args.url, audio_path)

    duracion_mb = audio_path.stat().st_size / (1024 * 1024)
    print(f"\nListo: {audio_path} ({duracion_mb:.1f} MB)")


if __name__ == "__main__":
    main()
"""clean.py
Aisla la voz (todos los hablantes juntos) del ruido/música de fondo usando
Demucs en modo 2 stems (vocals vs. el resto).
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

# Nombre de la carpeta temporal donde Demucs escribe antes de renombrar la voz.
_TMP_DIR = ".demucs_tmp"


def _check_demucs_installed() -> None:
    """Lanza un error claro si el paquete `demucs` no está disponible."""
    if importlib.util.find_spec("demucs") is None:
        raise RuntimeError(
        "demucs no está instalado. Actívalo con:\n"
        "  .venv/bin/python -m pip install torch torchaudio "
        "--index-url https://download.pytorch.org/whl/cpu\n"
        "  .venv/bin/python -m pip install demucs numpy\n"
        "y vuelve a ejecutar con --limpiar."
    )


def _find_vocals(tmp_dir: Path) -> Path:
    """Busca el vocals.wav generado por Demucs dentro de la carpeta temporal.

    Demucs produce <tmp>/htdemucs/<video>/vocals.wav (el subnivel del medio es
    el nombre del archivo de entrada sin extensión).
    """
    candidatos = list(tmp_dir.glob("*/*/vocals.wav"))
    if not candidatos:
        raise RuntimeError("Demucs terminó pero no generó vocals.wav.")
    return candidatos[0]


def clean_audio(audio_path: Path) -> Path:
    """Separa la voz del ruido/música y devuelve la ruta de vocals.wav.

    El archivo original queda intacto; la voz aislada se escribe junto a él en
    <misma carpeta>/vocals.wav. La ejecución tarda varios minutos en CPU.
    """
    _check_demucs_installed()

    dest_vocals = audio_path.parent / "vocals.wav"
    if dest_vocals.exists():
        print(f"  vocals.wav ya existe, se reutiliza -> {dest_vocals}")
        return dest_vocals

    print(f"  Separando voz con Demucs (modelo htdemucs) -> {dest_vocals}")
    print("  Nota: puede tardar varios minutos en CPU...")
    tmp_dir = audio_path.parent / _TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems=vocals",
        "-o", str(tmp_dir),
        str(audio_path),
    ]

    resultado = subprocess.run(cmd)
    if resultado.returncode != 0:
        raise RuntimeError("Demucs falló al separar la voz.")

    vocals = _find_vocals(tmp_dir)
    vocals.rename(dest_vocals)
    shutil.rmtree(tmp_dir)
    print(f"  Voz aislada -> {dest_vocals}")
    return dest_vocals
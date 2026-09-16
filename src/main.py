"""main.py
Punto de entrada del pipeline: clase principal que orquesta las fases.
"""

import argparse
import sys
from pathlib import Path

from src.clean import clean_audio
from src.download import download_audio, extract_video_id, fetch_title, sanitize_title


class Pipeline:
    """Orquestador principal del pipeline de frases a partir de videos."""

    def __init__(self, output_dir: str = "output", clean: bool = False) -> None:
        self.output_dir = Path(output_dir)
        self.clean = clean

    def download(self, url: str) -> Path:
        """Descarga el audio del video y devuelve la ruta del WAV generado.

        El directorio se nombra como "<título>__<video_id>" y el archivo de
        audio con solo el título saneado. Si no se pudo obtener el título,
        se cae al esquema por video_id.
        """
        video_id = extract_video_id(url)
        titulo_bruto = fetch_title(url)
        if titulo_bruto:
            titulo = sanitize_title(titulo_bruto)
            video_dir = self.output_dir / f"{titulo}__{video_id}"
            audio_path = video_dir / f"{titulo}.wav"
        else:
            video_dir = self.output_dir / video_id
            audio_path = video_dir / "video.wav"
        return download_audio(url, audio_path)

    def run(self, url: str) -> Path:
        """Ejecuta el pipeline completo y devuelve la ruta del resultado final.

        Descarga el audio y, con --limpiar, aísla la voz con Demucs. Las fases
        siguientes (diarizar, transcribir, segmentar, cortar y traducir) se
        irán añadiendo.
        """
        audio = self.download(url)
        if self.clean:
            audio = clean_audio(audio)
        return audio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline de frases a partir de videos de YouTube"
    )
    parser.add_argument("url", help="URL del video de YouTube")
    parser.add_argument(
        "--salida", default="output", help="Carpeta base de salida (default: output)"
    )
    parser.add_argument(
        "--limpiar",
        action="store_true",
        help="Aísla la voz del ruido/música con Demucs (lento en CPU)",
    )
    args = parser.parse_args(argv)

    pipeline = Pipeline(output_dir=args.salida, clean=args.limpiar)
    resultado = pipeline.run(args.url)
    size_mb = resultado.stat().st_size / (1024 * 1024)
    print(f"\nListo: {resultado} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
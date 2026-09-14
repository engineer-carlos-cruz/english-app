#!/usr/bin/env python3
"""
procesar_video.py
------------------
Prototipo Fase 1 del pipeline: dado un video de YouTube, genera un JSON con
frases completas (texto en inglés + traducción natural al español),
sus tiempos de inicio/fin, y un clip de audio individual por frase.

USO:
    python procesar_video.py "https://www.youtube.com/watch?v=XXXXXXXX"

REQUISITOS PREVIOS (instalar una sola vez):
    pip install yt-dlp openai-whisper anthropic pydub
    # además, ffmpeg debe estar instalado en el sistema:
    #   Mac:    brew install ffmpeg
    #   Ubuntu: sudo apt install ffmpeg
    #   Windows: https://ffmpeg.org/download.html

    export ANTHROPIC_API_KEY="tu_api_key_aqui"

SALIDA:
    output/<video_id>/
        video.wav              -> audio completo descargado
        frases.json            -> lista de frases con texto, tiempos y ruta de audio
        clips/frase_0001.mp3
        clips/frase_0002.mp3
        ...

NOTA: este script está pensado para correr en tu máquina local (necesita
salir a internet hacia YouTube y hacia la API de Anthropic), no dentro de
un sandbox con red restringida.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

WHISPER_MODEL_SIZE = "medium"     # tiny/base/small/medium/large-v2 (más grande = más preciso y más lento)
MIN_PALABRAS_POR_FRASE = 3        # frases más cortas que esto se fusionan con la siguiente
MARGEN_AUDIO_SEGUNDOS = 0.15      # margen extra al inicio/fin de cada clip para no cortar abrupto
TRADUCCION_LOTE = 15              # cuántas frases se traducen por llamada a la API (ahorra costo/tiempo)
CLAUDE_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Paso 1: obtener el video_id y descargar el audio con yt-dlp
# ---------------------------------------------------------------------------

def extraer_video_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if not match:
        raise ValueError(f"No pude extraer el video_id de la URL: {url}")
    return match.group(1)


def descargar_audio(url: str, destino_wav: Path) -> None:
    print(f"[1/5] Descargando audio con yt-dlp -> {destino_wav}")
    destino_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "-x", "--audio-format", "wav",
        "-o", str(destino_wav.with_suffix("")) + ".%(ext)s",
        url,
    ]
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"yt-dlp falló:\n{resultado.stderr}")
    if not destino_wav.exists():
        # yt-dlp a veces nombra distinto; buscar el .wav generado en la carpeta
        candidatos = list(destino_wav.parent.glob("*.wav"))
        if not candidatos:
            raise RuntimeError("No se encontró el archivo .wav descargado.")
        candidatos[0].rename(destino_wav)


# ---------------------------------------------------------------------------
# Paso 2: transcribir con Whisper (da segmentos ya aproximados a frases)
# ---------------------------------------------------------------------------

def transcribir(audio_path: Path) -> list[dict]:
    print(f"[2/5] Transcribiendo con Whisper (modelo={WHISPER_MODEL_SIZE})... esto puede tardar varios minutos")
    import whisper  # import diferido: es pesado de cargar

    modelo = whisper.load_model(WHISPER_MODEL_SIZE)
    resultado = modelo.transcribe(str(audio_path), language="en", verbose=False)
    segmentos = [
        {"texto": s["text"].strip(), "inicio": s["start"], "fin": s["end"]}
        for s in resultado["segments"]
        if s["text"].strip()
    ]
    print(f"      -> {len(segmentos)} segmentos crudos detectados")
    return segmentos


# ---------------------------------------------------------------------------
# Paso 3: post-procesar segmentos en frases completas
# ---------------------------------------------------------------------------

def fusionar_segmentos_cortos(segmentos: list[dict]) -> list[dict]:
    """Une segmentos muy cortos (pocas palabras, sin puntuación de cierre) con el siguiente."""
    frases: list[dict] = []
    buffer = None

    for seg in segmentos:
        if buffer is None:
            buffer = dict(seg)
        else:
            buffer["texto"] = f"{buffer['texto']} {seg['texto']}".strip()
            buffer["fin"] = seg["fin"]

        termina_con_puntuacion = buffer["texto"].rstrip().endswith((".", "?", "!"))
        suficientes_palabras = len(buffer["texto"].split()) >= MIN_PALABRAS_POR_FRASE

        if termina_con_puntuacion and suficientes_palabras:
            frases.append(buffer)
            buffer = None

    if buffer:  # lo que quede al final, aunque no cierre "perfecto"
        frases.append(buffer)

    print(f"[3/5] {len(frases)} frases completas tras fusionar segmentos cortos")
    return frases


# ---------------------------------------------------------------------------
# Paso 4: cortar el audio de cada frase con ffmpeg
# ---------------------------------------------------------------------------

def cortar_clips(audio_path: Path, frases: list[dict], carpeta_clips: Path) -> None:
    print(f"[4/5] Cortando {len(frases)} clips de audio con ffmpeg -> {carpeta_clips}")
    carpeta_clips.mkdir(parents=True, exist_ok=True)

    for i, frase in enumerate(frases, start=1):
        inicio = max(0, frase["inicio"] - MARGEN_AUDIO_SEGUNDOS)
        fin = frase["fin"] + MARGEN_AUDIO_SEGUNDOS
        nombre_clip = f"frase_{i:04d}.mp3"
        ruta_clip = carpeta_clips / nombre_clip

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio_path),
            "-ss", str(inicio), "-to", str(fin),
            str(ruta_clip),
        ]
        resultado = subprocess.run(cmd, capture_output=True, text=True)
        if resultado.returncode != 0:
            print(f"      ! Error cortando frase {i}: {resultado.stderr.strip()[:200]}")
            frase["ruta_audio"] = None
        else:
            frase["ruta_audio"] = str(ruta_clip)


# ---------------------------------------------------------------------------
# Paso 5: traducir con equivalencia natural usando la API de Claude
# ---------------------------------------------------------------------------

PROMPT_TRADUCCION = """Traduce al español cada una de las siguientes frases en inglés.
Usa el equivalente NATURAL que usaría un hispanohablante nativo, NO una traducción
literal palabra por palabra. Si es una expresión idiomática, usa el modismo
equivalente en español. Si el registro es informal, mantenlo informal.

Responde ÚNICAMENTE con un array JSON de strings, en el mismo orden que las frases
de entrada, sin explicaciones ni texto adicional. Ejemplo de formato de salida:
["traducción 1", "traducción 2", "traducción 3"]

Frases:
{frases_numeradas}
"""


def traducir_lote(cliente, frases_texto: list[str]) -> list[str]:
    frases_numeradas = "\n".join(f"{i+1}. {t}" for i, t in enumerate(frases_texto))
    prompt = PROMPT_TRADUCCION.format(frases_numeradas=frases_numeradas)

    respuesta = cliente.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    texto_respuesta = respuesta.content[0].text.strip()
    texto_respuesta = re.sub(r"^```json|```$", "", texto_respuesta.strip(), flags=re.MULTILINE).strip()

    try:
        traducciones = json.loads(texto_respuesta)
    except json.JSONDecodeError:
        print("      ! No se pudo parsear la respuesta como JSON, se guardan vacías para este lote")
        return ["" for _ in frases_texto]

    if len(traducciones) != len(frases_texto):
        print(f"      ! El lote devolvió {len(traducciones)} traducciones para {len(frases_texto)} frases, ajustando")
        traducciones = (traducciones + [""] * len(frases_texto))[: len(frases_texto)]

    return traducciones


def traducir_frases(frases: list[dict]) -> None:
    print(f"[5/5] Traduciendo {len(frases)} frases con Claude (lotes de {TRADUCCION_LOTE})")
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Falta instalar el paquete 'anthropic': pip install anthropic")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Falta la variable de entorno ANTHROPIC_API_KEY")

    cliente = anthropic.Anthropic()

    for i in range(0, len(frases), TRADUCCION_LOTE):
        lote = frases[i : i + TRADUCCION_LOTE]
        textos = [f["texto"] for f in lote]
        traducciones = traducir_lote(cliente, textos)
        for frase, trad in zip(lote, traducciones):
            frase["texto_espanol"] = trad
        print(f"      -> traducidas frases {i+1} a {i+len(lote)}")


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extrae frases, audio y traducciones de un video de YouTube")
    parser.add_argument("url", help="URL del video de YouTube")
    parser.add_argument("--salida", default="output", help="Carpeta base de salida (default: output)")
    args = parser.parse_args()

    video_id = extraer_video_id(args.url)
    carpeta_video = Path(args.salida) / video_id
    audio_path = carpeta_video / "video.wav"
    carpeta_clips = carpeta_video / "clips"
    ruta_json = carpeta_video / "frases.json"

    print(f"== Procesando video {video_id} ==")

    descargar_audio(args.url, audio_path)
    segmentos = transcribir(audio_path)
    frases = fusionar_segmentos_cortos(segmentos)
    cortar_clips(audio_path, frases, carpeta_clips)
    traducir_frases(frases)

    salida = {
        "video_id": video_id,
        "url": args.url,
        "total_frases": len(frases),
        "frases": frases,
    }
    ruta_json.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✔ Listo. {len(frases)} frases guardadas en: {ruta_json}")
    print(f"  Clips de audio en: {carpeta_clips}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✘ ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    
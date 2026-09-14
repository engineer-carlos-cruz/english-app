# Plan original: app de frases de YouTube

Plan Fase 1 del pipeline: dado un video de YouTube, generar un JSON con frases
completas (texto en inglés + traducción natural al español), sus tiempos de
inicio/fin, y un clip de audio individual por frase.

## Uso

```
python procesar_video.py "https://www.youtube.com/watch?v=XXXXXXXX"
```

## Requisitos previos

```
pip install yt-dlp openai-whisper anthropic pydub
# además, ffmpeg debe estar instalado en el sistema:
#   Mac:    brew install ffmpeg
#   Ubuntu: sudo apt install ffmpeg
#   Windows: https://ffmpeg.org/download.html

export ANTHROPIC_API_KEY="tu_api_key_aqui"
```

## Salida

```
output/<video_id>/
    video.wav              # audio completo descargado
    frases.json            # lista de frases con texto, tiempos y ruta de audio
    clips/
        frase_0001.mp3
        frase_0002.mp3
        ...
```

## Flujo original (5 pasos)

```
[1] descargar   yt-dlp -> video.wav
[2] transcribir whisper (modelo medium, language=en) -> segmentos
[3] fusionar    segmentos cortos en frases completas (heurística)
[4] cortar      clips MP3 por frase con ffmpeg
[5] traducir    frases al español con Claude (lotes de 15)
```

### Paso 1 — Descargar audio (yt-dlp)

Se extrae el `video_id` de la URL por regex (`v=`, `youtu.be/`, `shorts/`) y se
descarga solo el audio con:

```
yt-dlp -x --audio-format wav -o <carpeta>/video.%(ext)s URL
```

Si yt-dlp nombra distinto el archivo, se busca un `*.wav` en la carpeta y se
renombra a `video.wav`.

### Paso 2 — Transcribir (openai-whisper)

Se carga el modelo `medium` (tiny/base/small/medium/large-v2; más grande = más
preciso y más lento) y se transcribe el audio forzando idioma inglés:

- Devuelve **segmentos** con `texto`, `inicio` y `fin` (segundos).
- Los segmentos vacíos se descartan.
- Es un paso pesado: puede tardar varios minutos.

### Paso 3 — Fusionar segmentos en frases (heurística)

`fusionar_segmentos_cortos`:

1. Acumula segmentos en un buffer.
2. Cierra la frase solo cuando el texto acumulado:
   - termina en `.`, `?` o `!`, **y**
   - tiene ≥ `MIN_PALABRAS_POR_FRASE` (3) palabras.
3. El buffer restante al final se guarda igual, aunque no cierre "perfecto".

### Paso 4 — Cortar clips (ffmpeg)

Por cada frase se corta un `frase_NNNN.mp3` con un margen de
`MARGEN_AUDIO_SEGUNDOS` (0.15 s) al inicio y al final para no cortar abrupto:

```
ffmpeg -y -i video.wav -ss <inicio> -to <fin> clips/frase_NNNN.mp3
```

### Paso 5 — Traducir (Claude API)

En lotes de `TRADUCCION_LOTE` (15) se envía a Claude (`claude-sonnet-4-6`) el
prompt pidiendo:

- traducción **natural** que usaría un hispanohablante nativo (no literal),
- modismos equivalentes,
- mantener el registro (informal → informal),
- respondiendo solo con un array JSON de strings.

La respuesta se limpia de fences de código, se parsea como JSON y se ajusta a la
longitud del lote si hace falta. Requiere `ANTHROPIC_API_KEY`.

## Configuración (constantes del script)

| Constante | Valor | Descripción |
|---|---|---|
| `WHISPER_MODEL_SIZE` | `medium` | Tamaño del modelo Whisper |
| `MIN_PALABRAS_POR_FRASE` | 3 | Frases menores se fusionan con la siguiente |
| `MARGEN_AUDIO_SEGUNDOS` | 0.15 | Margen extra al cortar cada clip |
| `TRADUCCION_LOTE` | 15 | Frases por llamada a la API |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Modelo de traducción |

## Nota de ejecución

Script pensado para correr en la máquina local: necesita salir a internet hacia
YouTube y hacia la API de Anthropic, no dentro de un sandbox con red restringida.

## Limitaciones conocidas

- La segmentación depende de la puntuación que ponga Whisper (puede alucinar
  puntos o omitirlos) → frases larguísimas o divisiones raras.
- No separa la voz de la música ni distingue hablantes.
- `pydub` se listaba como requisito pero no se usa en el código.
- `large-v2` y modelos grandes requieren más RAM/tiempo en CPU.

> Este plan describe la implementación original (v1). La evolución de este flujo
> está en `docs/new-plan.md`.
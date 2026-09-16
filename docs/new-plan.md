# Plan del nuevo `procesar_video.py`

Pipeline Fase 1 mejorado: dado un video de YouTube, genera un JSON con frases
completas (inglés + traducción natural al español), tiempos de inicio/fin y un
clip MP3 por frase, con limpieza previa del audio para quedarse solo con la voz
principal y sin ruido/música de fondo.

## Objetivo

- Mayor precisión en la **conformación de frases** (timestamps a nivel de palabra,
  corte por pausa/puntuación real, no heurística ciega).
- **Limpieza de audio**: aislar la voz de la música/ruido y, en entrevistas,
  conservar solo al hablante principal.
- Todo **gratis y local** (la única parte de pago es la traducción con Claude).

## Hardware

- Ubuntu, Intel Core i5, **sin GPU utilizable**: la GTX 920M (2015, 2 GB VRAM,
  compute 5.0) no es soportada por PyTorch actual y no cabe ningún modelo.
  El pipeline corre 100% en CPU.
- Todo se instala en el venv del proyecto (`.venv/`) para no tocar el sistema
  (no hay permisos sudo). ffmpeg/ffprobe se obtienen estáticos vía
  `static-ffmpeg`.

## Dependencias

```
requirements.txt:
    yt-dlp
    faster-whisper          # reemplaza a openai-whisper
    demucs 2.0              # opcional: voice isolation (--limpiar)
    sherpa-onnx             # opcional: diarización (--diarizar)
    anthropic               # traducción con Claude

Sistema (sin sudo, vía pip en venv):
    static-ffmpeg           # proporciona binarios ffmpeg/ffprobe estáticos
```

Se eliminan `openai-whisper` (nunca se usa más) y `pydub` (se declaraba pero no
se usaba).

## Estructura de salida

```
output/<título saneaizado>__<video_id>/
    <título saneaizado>.wav   # audio original descargado
    vocals.wav               # voz aislada (solo con --limpiar)
    principal.wav            # solo hablante principal (solo con --diarizar)
    frases.json              # frases + tiempos + rutas de clips + metadatos
    clips/
        frase_0001.mp3
        frase_0002.mp3
        ...
```

El directorio combina título + video_id (legible, único y sin colisiones); el
WAV usa solo el título. Si no se obtiene el título, se cae al esquema por
video_id: `output/<video_id>/video.wav`.

## Flujo (6 fases)

```
[1] descargar      yt-dlp -> video.wav               (ya funciona en _test.py)
[2] limpiar        Demucs  -> vocals.wav             (flag --limpiar)
[3] diarizar       sherpa-onnx -> principal.wav      (flag --diarizar)
[4] transcribir    faster-whisper + VAD + word timestamps
[5] segmentar      frases a nivel de palabra (pausa + puntuación)
[6] cortar clips + traducir con Claude
```

---

### Fase 1 — Descargar audio (yt-dlp)

1. `extract_video_id(url)` — regex para el ID de 11 caracteres.
2. `fetch_title(url)` — `yt-dlp --print "%(title)s"` para obtener el título
   (solo metadata) y `sanitize_title(titulo)` para dejarlo seguro como nombre
   de archivo (quita `/\:*?"<>|`, colapsa espacios, recorta a ~80 chars).
3. `ruta_ffmpeg()` — llama a `static_ffmpeg.add_paths(weak=True)` y devuelve el
   directorio del binario (None si hay ffmpeg de sistema).
4. `download_audio(url, <título>.wav)`:
   ```
   yt-dlp -x --audio-format wav -o <carpeta>/<título>.%(ext)s URL
          [--ffmpeg-location <dir estático>]
   ```
5. Si yt-dlp nombró distinto, se busca `*.wav` en la carpeta y se renombra.

---

### Fase 2 — Limpiar audio (opcional, `--limpiar`)

Aísla la **voz** separándola de música/ruido/coros de fondo usando **Demucs v4
(htdemucs)** en modo 2 stems:

```
demucs --two-stems=vocals -o <carpeta> video.wav
# produce <carpeta>/htdemucs/video/vocals.wav -> se renombra a vocals.wav
```

Notas:
- Implementación vía `subprocess`, igual que ffmpeg/yt-dlp.
- **Lento en CPU** (varios minutos por canción); por eso es opcional y explícito.
- Modelo de separación por voz **≠** separación por hablante (eso es Fase 3).

---

### Fase 3 — Diarización (opcional, `--diarizar`)

Conserva **solo al hablante principal** (el que más tiempo habla) usando
`sherpa-onnx` offline (Apache-2.0, corre en CPU casi en tiempo real):

1. Cargar modelo de segmentación de hablantes
   (`pyannote-segmentation-3-0`, formato onnx de sherpa) + modelo de embeddings
   (`nemo-embedding-4-1`).
2. `VAD + Segmentation` produce segmentos con etiqueta de hablante (clustering).
3. Se elige el hablante con mayor duración total.
4. Se genera `principal.wav` concatenando solo esos intervalos (o cortando el
   resto); los demás hablantes quedan fuera.

Notas:
- Se asume `--diarizar` aplica sobre `vocals.wav` si también se usó `--limpiar`.
- Si son +3 hablantes la exactitud baja; suficiente para entrevistas 1 a 1.
- Los clips de frases del hablante secundario quedan descartados.

---

### Fase 4 — Transcribir (faster-whisper)

Reemplaza `openai-whisper` por **faster-whisper** (CTranslate2, ~4x más rápido en
CPU, misma precisión, menos RAM):

- Modelo por defecto: `small` (sweet spot en CPU i5). Opción `medium` vía flag
  `--modelo`.
- `vad_filter=True` + `vad_parameters={"min_silence_duration_ms": 400}` —
  Silero VAD integrado salta silencios → menos alucinaciones.
- `word_timestamps=True` — timestamps por palabra (base de la nueva segmentación).
- `language="en"`, `beam_size=5`, `condition_on_previous_text=True` para
  puntuación consistente.
- Devuelve **palabras** `(texto, inicio, fin, avg_logprob)` — no segmentos crudos.

---

### Fase 5 — Segmentar en frases (reemplaza la heurística)

Nuevo `segmentar_frases(palabras)` que trabaja a nivel de palabra:

1. Filtra palabras de baja confianza (`avg_logprob < -1.0`) para no contaminar.
2. Recorre palabras acumulando el buffer.
3. **Cierra frase** cuando la última palabra termina en `.`/`?`/`!` y se cumple
   alguna de:
   - pausa hacia la siguiente palabra > `UMBRAL_PAUSA` (~0.5 s), o
   - ya hay ≥ `MIN_PALABRAS_POR_FRASE` (3).
4. Tiempos exactos: `inicio` = primera palabra, `fin` = última palabra (más
   precisos que segmentos de Whisper).
5. Frases cortas que quedaron abiertas se fusionan con la siguiente (como antes).
6. Se guardan por frase: `texto`, `texto_espanol`, `inicio`, `fin`,
   `ruta_audio`, `confidence`, `speaker`.

Constantes configurables en cabecera:
`MIN_PALABRAS_POR_FRASE`, `UMBRAL_PAUSA_S`, `UMBRAL_LOGPROB`, `MARGEN_AUDIO_S`.

---

### Fase 6 — Cortar clips + traducir

- **Clips**: ffmpeg, igual que antes pero con timestamps exactos por palabra
  (+margen 0.15 s).
- **Traducción**: Claude por lotes de 15 (sin cambios de lógica). Se parsea la
  respuesta JSON robustamente y se guarda en `texto_espanol`.

---

## CLI final

```
python procesar_video.py URL [--salida output] [--modelo small|medium]
                           [--limpiar] [--diarizar]
```

- `--limpiar`  : aísla la voz (Demucs). Requiere instalar `demucs`.
- `--diarizar` : conserva solo al hablante principal (sherpa-onnx). Implica
  procesar sobre la pista de voz limpia si `--limpiar` está activo.

## Metadatos en frases.json

```json
{
  "video_id": "...",
  "url": "...",
  "total_frases": 0,
  "procesado": {
    "modelo_transcripcion": "small",
    "limpieza": true,
    "diarizacion": true
  },
  "frases": [...]
}
```

## Pasos de implementación

1. ✅ Crear `.venv`, instalar `yt-dlp` + `static-ffmpeg`, descargar binarios estáticos.
2. ✅ Crear `_test.py` con descarga de audio (probado con `OQq91b67U_c`, 23:02 min).
3. [ ] Instalar `faster-whisper`; reescribir `transcribir` (word timestamps + VAD).
4. [ ] Implementar `segmentar_frases` a nivel de palabra.
5. [ ] Añadir `limpiar_audio` (Demucs) con flag `--limpiar`.
6. [ ] Añadir `filtrar_hablante_principal` (sherpa-onnx) con flag `--diarizar`.
7. [ ] Conectar fases + flags en `main`; generar `requirements.txt`.
8. [ ] Pruebas: 1 video "persona sola" y 1 "entrevista"; validar frases y clips.

## Tradeoffs

- **CPU**: `medium` tarda ~10-20 min por video de 10 min; `small` es el balance.
- **Demucs en CPU**: más lento que el resto del pipeline; solo activarlo cuando
  hay música de fondo real.
- **Diarización**: precisa en 1-2 hablantes; no es un separador de "voz solista
  vs coro" (eso es Demucs).
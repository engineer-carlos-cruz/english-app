# AGENTS.md

Pipeline CLI in Python that turns YouTube videos into translatable English
phrase clips (audio → phrase JSON → Spanish translations). Spanish is the
working language: docstrings, comments, identifiers, CLI flags, and docs are in
Spanish. Write new code/docs in Spanish.

## Run

Run as a module from the repo root (plain `python src/main.py` breaks the
`from src.*` imports):

```bash
.venv/bin/python -m src.main "<youtube-url>" --salida output
# args are in Spanish: --salida (output dir)
```

Currently only the download phase is implemented (`Pipeline.run()` just calls
`download()`). Cleaning (Demucs), diarization (sherpa-onnx), transcription
(faster-whisper), and phrase segmentation are planned but **not built** — see
`docs/new-plan.md`.

## Dependencies & environment

- No `requirements.txt`/`pyproject` yet; deps are installed manually in `.venv`
  (Python 3.14). Installed so far: `yt-dlp`, `static-ffmpeg`.
- No sudo available: ffmpeg/ffprobe come from `static-ffmpeg` via
  `src/util/ffmpeg.py` (falls back to system ffmpeg if absent).
- Must run on the local machine: needs outbound network to YouTube and (later)
  the Anthropic API — not in a restricted sandbox.
- `ANTHROPIC_API_KEY` env var required for the translation phase.

## Output layout

`output/` is gitignored. A successful download produces
`output/<sanitized-title>__<video_id>/<title>.wav`; if the title can't be
fetched it falls back to `output/<video_id>/video.wav`.

## Architecture

- `src/main.py` — CLI entrypoint + `Pipeline` orchestrator.
- `src/download.py` — `extract_video_id`, `fetch_title`, `sanitize_title`,
  `download_audio` (wraps `yt-dlp -x --audio-format wav` via subprocess).
- `src/util/ffmpeg.py` — locates ffmpeg/ffprobe binaries.
- `docs/procesar_video.py` — old single-file prototype (reference only, not
  part of the `src` package). Check it for the planned translation/segmenting
  logic and constants.

## Conventions

- No tests, linter, or formatter config exist in the repo.
- External tools (yt-dlp, ffmpeg, and planned demucs/sherpa) are invoked via
  `subprocess`, not Python libraries.
# Colab Karaoke Video Generator

Prepare reusable audio stems and word-timed LyricsFile YAML on Colab, correct the result in the external
[LyricsEditor](https://dotslashgabut.github.io/lyricseditor/), then render ASS and video without repeating media
acquisition, source separation, alignment, or transcription.

## Quick path

```bash
uv sync --dev
uv run karaoke SOURCE --language en
# (Opcional) Ajustar estilos, fuentes y previsualizar en vivo:
uv run karaoke editor outputs/JOB_ID
# Corregir letras si es necesario en LyricsEditor:
# outputs/JOB_ID/lyrics.lyricsfile.yaml
# Renderizar video final en Colab:
uv run karaoke render outputs/JOB_ID
```

The preparation command finishes after downloading `outputs/JOB_ID`; no process remains paused. Open
[LyricsEditor](https://dotslashgabut.github.io/lyricseditor/) separately and:

1. Load `vocals.flac` as the audio file.
2. Load `lyrics.lyricsfile.yaml` as the lyrics file.
3. Review low-confidence words with `Alt+N` and `Alt+P`.
4. Export **LyricsFile YAML**.
5. Replace the job's `lyrics.lyricsfile.yaml` with the exported file.

## Live Style Editor & Preview

Customize typography, colors, outline, shadow, margins, and background overlay with instant zero-dependency live preview before rendering:

```bash
uv run karaoke editor outputs/JOB_ID
```

- **Live synchronized Canvas preview**: Plays local audio (`instrumental.flac` or `vocals.flac`) and animates the karaoke text wipe in real time at 60 FPS.
- **Typography & Styling**: Choose from popular web fonts or system fonts, adjust font size, line spacing, primary color, karaoke highlight color, outline width/color, and shadow depth/opacity.
- **Background Dimming**: Adjust overlay darkness slider for background images.
- **Instant Persistence**: Updates `job.json` and regenerates `.ass` subtitle files immediately.
- **Snapshot Export**: Download full-resolution PNG frames for visual QA.

Run `uv run karaoke render PATH_TO_JOB` only after the corrected file is in that prepared job folder. It validates the
folder and renders both the instrumental karaoke video and the original-audio lyrics video in one Colab session. Use
`--mode karaoke` or `--mode lyrics` only when one output is needed. Results are downloaded under
`JOB_DIR/renders/<timestamp>-<mode>/`:
- **Karaoke mode**: `{title}_karaoke.mp4` has clean background video without burned text, paired with
  `{title}_karaoke.ass` in the same directory. Long lines scroll horizontally during their sung interval while short
  lines remain centered.
- **Lyrics mode**: `{title}_lyrics.mp4` has static, wrapped subtitles burned in, with the raw subtitle file saved under
  `subtitles/{title}_lyrics.ass` to prevent media players from double-rendering subtitles.

## Lyrics strategy

Preparation selects the first usable source in this order:

1. A matching LRCLIB LyricsFile that already contains word timings.
2. LRCLIB line-synced or plain lyrics aligned to the separated vocal stem with CTC forced alignment.
3. Faster Whisper transcription with word timestamps when LRCLIB has no safe match or alignment fails.

Automatic LRCLIB matches evaluate track title, artist variants, duration, and song editions (such as Acoustic or Live)
through progressive discovery tiers (exact metadata, without album, primary artist, and structured search) while
strictly validating candidates to prevent mismatches. Use `--lrclib-id ID` to select a known record,
or `--no-lrclib` to force Faster Whisper. Local files and noisy video metadata can be corrected with `--title`,
`--artist`, and `--album`.

The CTC path pins `ctc-forced-aligner` and `MahmoudAshraf/mms-300m-1130-forced-aligner`. The package metadata and
model use **CC-BY-NC-4.0**, so this configuration is for non-commercial use only. Numeric tokens are aligned through
their spoken form and mapped back to the original text, so values such as `9:30` remain one editable LyricsFile word.
CTC leaves a free alignment segment between lyric units so pauses remain timing gaps instead of extending the previous
word.

Parenthesized spans are preserved as background vocals. Generated CTC lyrics use the neutral `v1` agent, add
`isBackground: true` to words inside parentheses, and keep the parentheses in the line text. Existing `agent` and
`isBackground` values from LRCLIB LyricsFile records are preserved; the pipeline does not attempt to identify singers
from plain lyrics.

## Prepared job

| File | Purpose |
|---|---|
| `job.json` | Durable media, source, alignment, video, and background configuration. |
| `lyrics.lyricsfile.yaml` | Canonical editable lyrics and word timings. |
| `vocals.flac` | Separated vocal stem recommended for alignment review. |
| `instrumental.flac` | Reusable accompaniment for karaoke renders. |
| `original_audio.*` | Original source used by lyrics-mode renders. |
| `alignment.json` | Original CTC or Whisper alignment evidence for diagnosis. |
| `background.*` | Copied background image when one was supplied. |

LyricsFile import accepts omitted `end_ms` values when the next word or line provides an unambiguous boundary.
Rendering is stricter: non-empty lines require words, positive durations, ordered timings within each vocal channel,
and confidence values between `0` and `1`. Timings may overlap across agents or between main and background vocals.
Explicit gaps between `end_ms` and the next `start_ms` remain silent in the karaoke effect.

## Preparation options

```bash
uv run karaoke ./song.flac --title "Song" --artist "Artist" --language en
uv run karaoke YOUTUBE_URL --lrclib-id 123456
uv run karaoke YOUTUBE_URL --no-lrclib --whisper-model large-v3
uv run karaoke ./song.flac --background-image ./background.png --resolution 720p
```

YouTube URLs copied with Windows-style escapes such as `watch\?v\=VIDEO_ID` are normalized automatically. Prefer the
canonical quoted form when entering a URL manually: `"https://www.youtube.com/watch?v=VIDEO_ID"`.

| Option | Default | Purpose |
|---|---:|---|
| `--language` | `en` | Whisper language code; CTC accepts common two-letter codes or ISO 639-3. |
| `--title` | source metadata | Track title override for LRCLIB. |
| `--artist` | source metadata | Artist override for LRCLIB. |
| `--album` | source metadata | Album override for LRCLIB. |
| `--lrclib-id` | automatic | Force one LRCLIB record. |
| `--no-lrclib` | disabled | Skip lyrics lookup and use Faster Whisper. |
| `--whisper-model` | `large-v3` | Faster Whisper fallback model. |
| `--demucs-model` | `htdemucs_ft` | Source separation model; `htdemucs` is faster. |
| `--resolution` | `1080p` | Resolution stored in the prepared job. |
| `--gpu` | `T4` | Colab GPU variant, subject to account availability. |
| `--auth` | `oauth2` | Colab CLI authentication; `adc` is also supported. |
| `--timeout` | `14400` | Remote timeout in seconds. |
| `--no-cookies` | disabled | Do not upload the local cookies file. |

When `--language auto` is used and the source metadata does not identify a language, preparation uses the Faster
Whisper fallback because CTC requires an explicit ISO language code.

Preparation always stops before rendering so LyricsEditor corrections remain an explicit human approval step.

## Authentication

Confirm the project-managed Colab CLI is authenticated:

```bash
uv run colab version
uv run colab sessions
```

Set `HF_TOKEN` in `.env` or the shell when Hugging Face downloads require authentication. Cookies default to the
ignored project file `cookies.txt`. Both are credentials and must not be committed or published.

If Colab reports `HTTP 412 Precondition Failed` or `TooManyAssignmentsError`, stop an existing named runtime:

```bash
uv run colab stop --session SESSION_NAME
```

If `uv run colab sessions` shows an assignment named `[?]`, the server still has a runtime that is missing from the
local session state. Release it by replacing `ENDPOINT` with the endpoint printed after `[?]`:

```bash
uv run python -c "from colab_cli.common import state; state.client.unassign('ENDPOINT')"
uv run colab sessions
```

The project pins `google-colab-cli==0.6.0` with `jupyter-kernel-client==0.15.0` because that CLI still uses the
pre-1.0 kernel client API.

## Limits

- LyricsEditor is external and browser-sandboxed; exported YAML must be moved back into the prepared job manually.
- Agents and overlapping background vocals are supported, but automatic singer identification, translations, and
  romanization are out of scope.
- LRCLIB matching can fail for incomplete or noisy source metadata; use `--lrclib-id` when exact selection matters.
- Music audio and lyrics may receive Content ID claims, regional blocks, or takedown requests.
- Colab transfer size and concurrent runtime limits depend on the account.

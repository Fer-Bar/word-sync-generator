# Colab Karaoke Video Generator

This project sends audio processing to a Google Colab GPU and downloads every final artifact to the local `outputs/`
directory. It does not mount or use Google Drive.

## Quick Start

1. Install the project and its pinned Colab CLI dependencies:

   ```bash
   uv sync --dev
   ```

2. Confirm that the project-managed Colab CLI is available and authenticate if needed:

   ```bash
   uv run colab version
   ```

   To authenticate Hugging Face model downloads, set `HF_TOKEN` in the project `.env` or in the shell environment. The
   CLI sends only the token to the ephemeral Colab runtime and removes the temporary remote token file before loading
   models. Never commit or publish the token.

3. Generate videos from YouTube:

   ```bash
   uv run karaoke "https://www.youtube.com/watch?v=VIDEO_ID"
   ```

4. Generate videos from a local audio or video file:

   ```bash
   uv run karaoke ./song.mp3
   ```

The command creates a T4 session, uploads the required files, installs the pinned remote dependencies, executes the
pipeline, downloads a ZIP, extracts it under `outputs/<job-id>/`, and stops the Colab session.

Subtitle paging is automatic; the standard commands above do not require synchronization or alignment flags.

## Colab Sessions

The number of simultaneous runtimes depends on the Colab account. If the account only supports one runtime, stop any
existing session before starting a karaoke job:

```bash
uv run colab sessions
uv run colab stop --session SESSION_NAME
```

An `HTTP 412 Precondition Failed` or `TooManyAssignmentsError` means the account already has the maximum number of
active runtimes. If `uv run colab sessions` shows an unnamed session (`?`), terminate it from Colab's runtime management
page because the CLI cannot address it by a local session name.

## Backgrounds

The default background is solid dark navy (`#0B1020`). This keeps lyrics readable and produces a smaller video than a
detailed moving background.

Use another solid color:

```bash
uv run karaoke ./song.mp3 --background-color "#171717"
```

Use a local image:

```bash
uv run karaoke ./song.mp3 --background-image ./background.png
```

Image backgrounds are cropped to fill the frame and receive a dark overlay before subtitles are rendered. Only use
images you created or have permission to reuse.

## Common Options

| Option | Default | Purpose |
|---|---:|---|
| `--language` | `en` | Whisper language code. Use `auto` for detection. |
| `--whisper-model` | `large-v3` | Faster Whisper model. |
| `--demucs-model` | `htdemucs_ft` | Vocal separation model. Use `htdemucs` for a faster run. |
| `--resolution` | `1080p` | Output resolution. `720p` reduces time and file size. |
| `--gpu` | `T4` | Colab GPU variant. Availability depends on the account. |
| `--auth` | `oauth2` | Colab CLI authentication strategy. `adc` is also supported. |
| `--timeout` | `14400` | Maximum remote execution time in seconds. |
| `--no-cookies` | disabled | Run yt-dlp without the local cookies file. |

## Local Artifacts

Each output directory contains:

- `*_karaoke.mp4`: instrumental audio with karaoke highlighting.
- `*_lyrics.mp4`: original audio with karaoke highlighting.
- `*_instrumental.flac`: lossless instrumental stem.
- `*_transcript.json`: editable application-owned word timestamps.
- `*_karaoke.ass`: rendered subtitle source.
- `manifest.json`: job configuration and artifact metadata.

Temporary source audio, vocal stems, models, and cookies remain on the ephemeral Colab VM and are removed when the
session stops.

## Subtitle Behavior

Production transcription uses one Faster Whisper pass with Silero VAD and word timestamps. Those words are grouped into
lyric lines at 42 characters, sentence-ending punctuation, or gaps longer than 0.8 seconds. Consecutive lines form
centered, timing-aware pages with at most three explicit lines. A new page starts before a silence of 1.5 seconds, before
a fourth line, or before the page would exceed 15 seconds.

Each ASS page requests short lead and tail visibility with fade-in and fade-out. Available lead or tail time is shortened
at the start of the track or when an overlapping schedule requires a shared boundary; page display windows never overlap.
For non-overlapping source timestamps, karaoke highlighting follows absolute word starts after ASS centisecond
quantization. Words that quantize to the same instant are serialized in transcript order with a minimum one-centisecond
duration. If source words overlap across a page boundary, non-overlapping ASS dialogues cannot represent both timestamps
simultaneously: the earlier page finishes its complete schedule, then the following page starts immediately and delays
overlapping words by the minimum required time. Segments without words are skipped. Review `*_transcript.json` and
`*_karaoke.ass` when speech recognition needs manual correction; no subtitle strategy can infer reliable lyrics from
every vocal mix.

WhisperX forced alignment is intentionally not the production default. The full alignment experiment is preserved on
`experiment/whisperx-alignment` at commit `85f2d93` for future research without adding its runtime or dependencies to
the main pipeline.

## Planned Editor

The manual timing editor is paused and not yet available. See the [editor progress plan](docs/editor-progress.md).

## Dependency Choices

The project pins `google-colab-cli==0.6.0` with `jupyter-kernel-client==0.15.0`. Colab CLI 0.6.0 still uses the pre-1.0
`KernelClient` API, so newer `jupyter-kernel-client` releases fail during remote execution. Keep this pin until Colab CLI
publishes a release compatible with the 1.x API.

`faster-whisper` replaces `stable-ts`. It is maintained, uses CTranslate2 for efficient GPU inference, supports Silero
VAD, and returns word-level timestamps directly. The project owns the transcript and ASS formats so a future editor or
alignment engine can be introduced without changing stored jobs.

Demucs remains the separation engine. `htdemucs_ft` prioritizes quality and is approximately four times slower than
`htdemucs`.

## Cookies

The default cookies path is `cookies.txt` at the project root. The file is ignored by Git and is never included in
downloaded artifacts. Cookies are account credentials: do not commit, publish, or paste their contents. Export fresh
cookies if YouTube rejects the current session.

## Current Limits

- Colab CLI uploads and downloads files through the notebook contents API. Large local videos or result archives may
  use significant local memory during transfer.
- Lyrics are generated by speech recognition. Singing, backing vocals, and repeated choruses still require manual
  review.
- Editing and re-aligning `*_transcript.json` is reserved for the next phase.
- Music audio and lyrics may still receive Content ID claims, regional blocks, or takedown requests.

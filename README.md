# Colab Karaoke Video Generator

Prepare audio and word timings on Colab, correct them in a local React editor, then render the final video on Colab without repeating acquisition, Demucs, or Whisper.

## Happy path

```bash
uv sync --dev
uv run karaoke SOURCE
uv run karaoke edit outputs/JOB_ID
uv run karaoke render-colab outputs/JOB_ID --mode karaoke
```

The preparation command downloads a durable job under `outputs/<job-id>/`. The editor saves only when you press **Save** or `Ctrl/Cmd+S`. The render command uploads that existing job state and downloads an MP4 and its ASS file under `JOB_DIR/renders/`.

Use `--mode lyrics` to render with the original audio instead of the instrumental stem.

## Prepared job

Each job contains:

- `original_audio.*`: the source audio used by the editor and lyrics render.
- `instrumental.flac`: the reusable Demucs instrumental stem.
- `original_transcript.json`: the unchanged Faster Whisper result.
- `edit.json`: canonical, revisioned editor state.
- `manifest.json`: source, configuration, and artifact metadata.
- `background.*`: the copied background image, when supplied.

Preparation stops before video rendering by default. Use `--render-now` only when both initial videos are required immediately.

## Editing

The local editor is audio-first. It supports word correction and removal, line split/move/merge operations, line-only gap normalization, start/end nudging, playhead assignment, replay/loop, and atomic undo/redo.

For a sustained vowel, enter a joined fragment pattern such as `am|o|r`. The fragments must concatenate exactly to the displayed word. Their internal boundary times control ASS highlighting while the rendered text remains `amor`.

`karaoke edit` binds its FastAPI backend to loopback, generates a temporary API token, and starts the already-installed Vite executable when available. If Vite is unavailable, it serves an existing `editor/dist` build. It never builds automatically.

## Preparation options

```bash
uv run karaoke ./song.mp3 --language auto --resolution 720p
uv run karaoke ./song.mp3 --background-color "#171717"
uv run karaoke ./song.mp3 --background-image ./background.png
```

| Option | Default | Purpose |
|---|---:|---|
| `--language` | `en` | Whisper language code; use `auto` for detection. |
| `--whisper-model` | `large-v3` | Faster Whisper model. |
| `--demucs-model` | `htdemucs_ft` | Separation model; `htdemucs` is faster. |
| `--resolution` | `1080p` | Render resolution stored in the job. |
| `--gpu` | `T4` | Colab GPU variant, subject to account availability. |
| `--auth` | `oauth2` | Colab CLI authentication; `adc` is also supported. |
| `--timeout` | `14400` | Remote timeout in seconds. |
| `--no-cookies` | disabled | Do not upload the local cookies file. |

## Authentication and Colab sessions

Confirm the project-managed CLI is authenticated:

```bash
uv run colab version
uv run colab sessions
```

Set `HF_TOKEN` in `.env` or the shell when Hugging Face model downloads require authentication. Cookies default to the ignored project file `cookies.txt`. Both are credentials: never commit or publish them.

If Colab reports `HTTP 412 Precondition Failed` or `TooManyAssignmentsError`, stop an existing named runtime with:

```bash
uv run colab stop --session SESSION_NAME
```

The project pins `google-colab-cli==0.6.0` with `jupyter-kernel-client==0.15.0` because that CLI still uses the pre-1.0 kernel client API.

## Limits

- Singing, backing vocals, and repeated choruses still require manual transcript review.
- Colab transfer size and concurrent runtime limits depend on the account.
- Music audio and lyrics may receive Content ID claims, regional blocks, or takedown requests.

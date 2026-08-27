# Karaoke transcript editor

This React application corrects the lyrics and timing in a prepared karaoke job. FastAPI only loads audio, returns the canonical document, and handles explicit revisioned saves.

## Open a prepared job

From the repository root:

```bash
uv run karaoke edit outputs/JOB_ID
```

The command reuses `editor/node_modules/.bin/vite` for development. If Vite is not installed, it serves an existing `editor/dist` build. It does not install dependencies or build the frontend.

Press **Save** or `Ctrl/Cmd+S` to update `edit.json`. There is no autosave. A stale revision is rejected so another write cannot be overwritten silently.

## Editing model

- Select a word to correct its text or timestamps.
- Set start/end from the audio playhead or nudge either boundary by 0.01 or 0.05 seconds.
- Split a line before the selection, move the word to the next line, merge with the next line, or normalize only the selected line's gaps.
- Replay or loop the selected word and use undo/redo for transcript operations.
- Enter `am|o|r` to split `amor` into timed fragments. The joined fragment text must remain exactly `amor`.

Local audio and transcript files can also be loaded for temporary inspection, but only prepared jobs have a canonical Save target.

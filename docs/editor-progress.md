# Paused timing editor plan

## Status

The web editor slice 1 is implemented on the `feat/web-editor` branch under the `editor/` directory using React 19, TypeScript, Tailwind CSS v4, and Vite with `pnpm`. It operates 100% in-browser with zero backend dependencies.

## Preserved work

| Work | Location | Use |
|---|---|---|
| WhisperX alignment experiment | `experiment/whisperx-alignment` at `85f2d93` | Research reference only |
| Local Python HTTP editor prototype | `wip/editor-prototype` at `95b9f61` | Rejected implementation reference only |

The WIP branch is not delivery-ready and is not merge material. Audits found blockers including save races,
non-transactional transcript/ASS publication, filesystem containment risks, cross-process lost updates, unbounded timing
values, inconsistent segment summaries, and missing observable HTTP/JavaScript coverage.

The prototype was not missing a UI: it already included HTML, CSS, and JavaScript. The overengineering came from the
custom Python HTTP/file server and its backend contracts for loading, validating, streaming, and saving local files.

## Current decision

Build the first editor slice as a frontend-only React application emitted as static assets. It has no application
backend. Vite is a likely build tool, but that dependency choice is not committed.

The browser should:

1. Select a transcript and reference video through file inputs and the File API.
2. Play the selected video through a temporary `URL.createObjectURL` URL.
3. Track the active word with `requestAnimationFrame` while playback is running.
4. Apply word or whole-segment time shifts in memory while preserving immutable word IDs.
5. Validate the complete edited transcript in memory.
6. Download edited JSON and ASS as Blob files without overwriting either source file.

This targets the observed use case: correcting a few timing offsets. Initial editing is limited to word and segment time
shifts; text editing, splitting, and merging are excluded.

## When a backend becomes justified

A backend should be introduced only when a confirmed requirement needs at least one of these capabilities:

- Direct writes to the local filesystem.
- Local or remote `ffmpeg` execution.
- Colab job orchestration.
- Collaboration, authentication, or authorization.
- Server-side storage or secrets.

All five are explicit non-goals for slice 1. Until one is required, a backend adds contracts and failure modes without
improving the timing-correction workflow.

## Suggested React boundaries

Keep transcript rules framework-independent and pure where practical:

- Parse and normalize application-owned transcript JSON.
- Shift one word or every word in a segment without changing IDs.
- Validate timing and structural invariants.
- Serialize edited transcript JSON and generated ASS.
- Resolve the active word for a playback timestamp.

Suggested component responsibilities:

| Boundary | Responsibility |
|---|---|
| File selection | Accept transcript and video files; report parsing or media errors |
| Video player | Own the object URL and expose playback time updates |
| Timeline/list | Display segments and words, active state, and timing values |
| Timing controls | Apply bounded word or segment shifts through explicit actions |
| Validation summary | Present blocking errors before export |
| Export controls | Create edited JSON and ASS downloads |

Use `useReducer` or an equivalent explicit state transition model. Keep source data, edits, playback state, and
validation results distinguishable; do not use global mutable state. WaveSurfer v7 may be added behind a small adapter
after the core workflow works. Domain functions must not depend on WaveSurfer or React.

## User flow

1. Open the static editor locally.
2. Select an application-owned `*_transcript.json` file.
3. Select the matching reference video.
4. Review synchronized words during playback.
5. Select a word or segment and shift its timing earlier or later.
6. Resolve every validation error.
7. Download new edited JSON and ASS files.
8. Keep the original transcript and video unchanged.

## Validation invariants

Export is blocked unless all of these hold:

- Every segment and word retains its immutable ID, with no duplicates or omissions.
- Timing values are finite, bounded integers in milliseconds.
- Every interval has `start_ms >= 0` and `end_ms > start_ms`.
- Word order remains deterministic and valid for ASS generation.
- Segment bounds consistently contain or derive from their words.
- Required transcript schema fields and supported schema version are present.
- Generated ASS is based on the same validated in-memory snapshot as the JSON download.

Validation should report actionable locations and reasons. It must never repair ambiguous data silently.

## Outputs

- A newly downloaded edited transcript JSON file.
- A newly downloaded ASS subtitle file generated from the same in-memory snapshot.

Downloads should use distinguishable names such as `*_edited.json` and `*_edited.ass`. Source files are read-only from
the editor's perspective and are never overwritten.

## Acceptance criteria

- The editor runs from static assets with no application server.
- A user can load a transcript and reference video without uploading either file.
- Playback highlights the active word accurately enough for manual review.
- A user can shift one word or all words in a segment while IDs and text remain unchanged.
- Invalid edits block both downloads and identify the affected data.
- JSON and ASS exports represent one validated state and leave source files untouched.
- Core transcript behavior has framework-independent tests.
- The first useful workflow works without WaveSurfer.

## Non-goals for slice 1

- Transcript text editing, word insertion/deletion, split, or merge.
- Automatic alignment or transcription.
- A Python, Node, or other application backend.
- Direct filesystem writes, `ffmpeg`, or Colab execution.
- Accounts, collaboration, server storage, or secrets.
- A full waveform editing suite or a fork of an existing subtitle editor.
- Replacing the stable CLI or renderer.

## Resume checklist

- [ ] Start from clean `main` at or after baseline `9c0e24b`.
- [ ] Reconfirm the application-owned transcript schema and ASS generation rules.
- [ ] Define fixtures for valid transcripts and each validation failure.
- [ ] Choose the React static build setup; evaluate Vite without treating it as preselected.
- [ ] Implement and test framework-independent transcript operations first.
- [ ] Build the file-selection, playback, timing-shift, validation, and export path.
- [ ] Verify object URLs are revoked and no selected data leaves the browser.
- [ ] Consider a WaveSurfer v7 adapter only after core acceptance criteria pass.

## Reviewable work units

1. **Domain foundation:** transcript parsing, immutable shifts, validation, ASS serialization, and focused tests.
2. **Static shell:** React entry point, file selection, reducer state, and clear load errors.
3. **Playback review:** object-URL video playback and `requestAnimationFrame` active-word tracking.
4. **Timing correction:** word and segment shift controls with validation feedback.
5. **Safe export:** paired JSON/ASS Blob downloads from one validated snapshot.
6. **Optional enhancement:** evaluate WaveSurfer v7 through an isolated adapter.

Each unit should remain independently reviewable and keep its tests or verification evidence with the behavior it adds.

## Research summary

Do not fork a full subtitle editor for this narrow correction workflow; the inherited feature surface and data model would
cost more than the required behavior. WaveSurfer v7 can improve navigation later, but it is optional infrastructure, not
the foundation of the editor.

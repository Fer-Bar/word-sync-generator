# YouTube inputs and custom notebook backgrounds

## Scope

User requested YouTube video download with metadata, real CLI execution, optional
`cookies.txt` when required, and video/image/solid-color backgrounds. Keep manual wheel
upload for now. Branch: `feat/colab-youtube-backgrounds`; baseline: `b2f59bc`.

## Implementation

- Step 2 chooses local upload or one YouTube video, with native optional cookies upload.
  The shared downloader retains audio-only CLI defaults; notebook requests video up to
  720p. Normalize watch/short/live/embed links to one canonical video, rejecting channels
  and playlists. Resolve editable musical metadata through the existing identity service.
- Temporary cookies are copied outside the media/project and removed after use. The
  original local file is not modified; raw yt-dlp metadata is not exported with the project.
- Optional cell 4c selects color, uploaded image/video, or source video. Existing visual
  validation/configuration and render services handle the assets and saved settings.
  Custom backgrounds override the chosen preset's background, preserving its typography.
- Package 0.1.1 adds `youtube` and `configure` adapter operations. Setup checks capabilities
  and always requests a fresh wheel selection, avoiding reuse of an old runtime upload.
- Removed the non-musical `(Lyric Video)` suffix during shared song-title inference after
  observing it in the actual download; preserve live/remix/edition names.

## Execution evidence

- After the user authorized session disconnection, the server listed no active runtimes.
  Created dedicated `karaoke-yt-backgrounds-20261110` successfully without stopping any
  user session. Uploaded the final 0.1.1 wheel and notebook. Isolated setup installed
  128 packages, dependency validation passed, and diagnosis reported Tesla T4. Actual
  anonymous YouTube acquisition was rejected with the sign-in/bot-check message.
  Authorized cookies retry succeeded through the public adapter: full 30.7 MB video,
  download progress and title/artist reached the notebook. Uploaded cookies were removed
  in `finally`. The actual preparation cell completed with English/Whisper small and
  LRCLIB returned 43 lines. Whisper and the CTC model loaded on CUDA; final timing
  provenance is `faster-whisper` / `estimated`, with `needs_review: true` after recovery.
  This is not timing-accuracy acceptance. Three remote full-song renders completed and
  decoded: H.264/AAC, 1280×720, 173.333333 seconds each, Lyrics/Clásico. Saved settings
  confirm solid, image and video backgrounds; the eight-second video clip loops across
  the complete song. Download hashes match the remote outputs and the installed wheel.
  The editable ZIP includes current lyrics and the saved video background, with no cookies
  or raw acquisition metadata. Verified uploaded cookie removal. Dedicated session stop
  returned **Session terminated** after recovering all artifacts.
  An earlier
  proof-script replacement missed the browser upload call and timed out waiting for
  browser input; that was a harness error, not a download result. Restarted only the
  dedicated kernel and reused installed packages before the corrected retry.

- Real local YouTube acquisition succeeded for `xZqCk1gl4tg`: Jorja Smith / What's Done
  Is Done, 173.321 seconds, 1280×720 AV1/Opus in MP4. Album unavailable and left editable.
  Anonymous local download succeeded; authenticated Colab acquisition is recorded above.
- Dedicated T4 allocation `karaoke-yt-backgrounds-20261110` failed with HTTP 412 /
  `TooManyAssignmentsError`. The existing browser T4 was not stopped or modified.
- Full-song local shared-renderer executions with the previously generated Ocean Eyes
  timings and real audio completed for solid/image/video backgrounds. All three outputs
  decoded completely: H.264/AAC, 1280×720, approximately 199.545 seconds (video background
  output 199.584 seconds). The 173.321-second YouTube video loops to cover the song.
  This invokes the real shared FFmpeg renderer locally, not the remote notebook launcher.
- Wheel 0.1.1 built and installed into isolated scratch; its public `youtube` operation
  completed real acquisition and returned the cleaned title and artist.
- Python/notebook compilation and Ruff passed. No tests or mocks run in this slice.
- Private evidence: `/tmp/opencode/karaoke-youtube-backgrounds-20261110/`.
- Official `dist/` now contains the new notebook and wheel 0.1.1 (SHA-256
  `2a985ebeeed65699ce3fa9ed70c9906830c5f2652e29e31d1dc5968dae09b6f9`).
  The downloaded video is in `dist/audio/`; three completed renders are in
  `dist/results/backgrounds/`. The previous pair was archived outside the repository.
- Hosted outputs are in `dist/results/youtube-backgrounds/`: three MP4s, vocals, current
  YAML and `Jorja_Smith_project.zip`. These are the final real Colab evidence, distinct
  from the earlier local Ocean Eyes renders. No implementation changes were needed after
  the tested wheel was built; commit `f51d498` remains the implementation candidate.

## Remaining

- Human timing review and browser control acceptance remain. Cookie-required acquisition
  and full hosted rendering now have direct execution evidence. The source files for
  image/video backgrounds were staged programmatically; this does not prove browser uploads.

# Media, transfers and retention

The project keeps three different audio assets: the source mix, vocals and
instrumental. They are not duplicate recordings. Keep these project assets if
you want to edit timing, regenerate a video or switch between lyrics and karaoke.
Rendering never deletes the user's input, project audio or exported videos.

## Transfer only what is needed

- Local video is reduced to its first audio stream before upload. Video,
  subtitles, extra audio tracks and container metadata are not transferred.
  Existing projects containing video get the same treatment when rendering.
- FLAC is reused as-is. Integer WAV PCM up to 24 bits is compressed losslessly to
  FLAC. Other audio codecs, including float PCM, are copied without changing the
  codec, sample rate or channel layout. MP4/MP3/Ogg/WebM retain an audio-only version of
  their original container to preserve encoder delay; other formats use Matroska
  audio (`.mka`) where possible. Unsupported
  remuxes fail before starting Colab rather than silently reducing quality.
- A render uploads only the mix for lyrics, only the instrumental for karaoke,
  or both for `--mode both`. Identical audio bytes share one ZIP member. Vocals
  are not sent for rendering. Background videos remain video.
- Transfer copies are private temporary files and disappear when the client
  operation finishes or fails. Input files are never rewritten in place.

## Cache policy

There is **no persistent acquisition/media cache**. Its budget is zero between
successful runs: sources and models are not kept in a new hidden media cache.
Rerendering reuses the project's existing audio rather than downloading the
source again. A failed preparation may need a fresh source download on retry.

Each remote operation has its own disposable workspace. Decoded mixture and
Demucs WAVs are removed after successful separation/compression. Alignment reads
the lossless vocal FLAC. Once the final ZIP is committed, the run's extracted
inputs, compressed intermediates and unpacked output copies are removed. This
cleanup never scans or prunes a project, another run, old output directories or
user exports. The final ZIP is kept for download. Upload ZIPs use fixed transport
names and last only for that runtime; a normal CLI invocation stops its runtime.

Failed or interrupted remote runs retain their owned workspace for recovery;
they are not a reusable cache and are not automatically aged out. The log prints
its path. Keep the checkpoint/results you need before manually removing that
failed run directory or resetting the runtime. Client `.recovery` directories
also remain on failure. A forced process kill can leave temporary files behind;
a successful future run never silently deletes these recovery files.

No TTL or size limit applies to project assets or exports. Cleaning creative
outputs requires an explicit user action, separate from disposable-media cleanup.

"""Validate uploaded media before starting the notebook's preparation pipeline."""

import json
import math
import subprocess
from pathlib import Path

from karaoke_app.lyric_references import plain_lines

MEDIA_EXTENSIONS = frozenset({".wav", ".flac", ".mp3", ".m4a", ".ogg", ".mp4", ".webm"})


def validate_inputs(paths: list[Path]) -> dict:
    """Inspect one media input and optional UTF-8 lyrics, without modifying either."""
    paths = [Path(path).expanduser().resolve() for path in paths]
    if any(not path.is_file() for path in paths):
        raise ValueError("An uploaded file is missing. Select the files again.")
    if any(path.suffix.lower() not in MEDIA_EXTENSIONS | {".txt"} for path in paths):
        raise ValueError("Supported files: WAV, FLAC, MP3, M4A, OGG, MP4, WEBM, and optional TXT lyrics.")
    media = [path for path in paths if path.suffix.lower() in MEDIA_EXTENSIONS]
    references = [path for path in paths if path.suffix.lower() == ".txt"]
    if len(media) != 1 or len(references) > 1:
        raise ValueError("Select exactly one audio/video file and at most one optional lyrics TXT.")
    source = media[0]
    if not source.stat().st_size:
        raise ValueError("The media file is empty. Select a valid audio or video file.")
    if references:
        try:
            text = references[0].read_text(encoding="utf-8-sig")
        except UnicodeError:
            raise ValueError("The optional lyrics file must be UTF-8 text.") from None
        if not plain_lines(text):
            raise ValueError("The optional lyrics file contains no lyric lines.")
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,format_name:format_tags:stream=codec_type,codec_name:stream_tags",
             "-of", "json", str(source)], capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("FFprobe is required to validate media. Complete notebook setup first.") from None
    except subprocess.TimeoutExpired:
        raise ValueError("Media inspection timed out. Try another local audio or video file.") from None
    if result.returncode:
        raise ValueError("Cannot read this media file. Its extension alone does not establish a valid format.")
    report = json.loads(result.stdout)
    streams = report.get("streams", [])
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if audio is None or not audio.get("codec_name"):
        raise ValueError("The selected file has no readable audio stream.")
    try:
        duration = float(report.get("format", {}).get("duration", "nan"))
    except (TypeError, ValueError):
        duration = math.nan
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("The selected file has no valid positive duration.")
    tags = {
        key.casefold(): " ".join(value.split())
        for group in (audio.get("tags", {}), report["format"].get("tags", {}))
        for key, value in group.items() if isinstance(value, str)
    }
    return {
        "source": str(source), "lyrics_text": str(references[0]) if references else None,
        "metadata": {"title": tags.get("title"), "artist": tags.get("artist") or tags.get("iaar"),
                     "album": tags.get("album")},
        "media": {"duration_seconds": duration, "format": report["format"].get("format_name"),
                  "audio_codec": audio["codec_name"],
                  "has_video": any(stream.get("codec_type") == "video" for stream in streams)},
    }

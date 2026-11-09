"""Prepare disposable, audio-only inputs without changing the user's media."""

import hashlib
import logging
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg

LOGGER = logging.getLogger(__name__)


def _integer_wave(source: Path) -> bool:
    try:
        with wave.open(str(source), "rb") as audio:
            return audio.getcomptype() == "NONE" and audio.getsampwidth() <= 3
    except (wave.Error, EOFError):
        return False


def prepare_audio_transfer(source: Path, directory: Path) -> Path:
    """Reuse FLAC or create one lossless audio-only asset in caller-owned scratch.

    Integer PCM up to 24 bits is compressed to FLAC. Other codecs, including
    floating-point PCM, are copied without resampling or re-encoding. MP4,
    MP3, Ogg and WebM retain their audio container's gapless/priming information.
    The original file is never changed or removed.
    """
    source = source.resolve(strict=True)
    with source.open("rb") as stream:
        if stream.read(4) == b"fLaC":
            return source
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    compress = _integer_wave(source)
    containers = {".mp4": ("m4a", "mp4"), ".m4a": ("m4a", "mp4"), ".mov": ("m4a", "mp4"),
                  ".m4v": ("m4a", "mp4"), ".aac": ("m4a", "mp4"), ".mp3": ("mp3", "mp3"),
                  ".webm": ("webm", "webm"), ".ogg": ("ogg", "ogg"), ".opus": ("ogg", "ogg"),
                  ".wav": ("wav", "wav"), ".aiff": ("aiff", "aiff"), ".aif": ("aiff", "aiff")}
    extension, container = ("flac", "flac") if compress else containers.get(source.suffix.lower(), ("mka", "matroska"))
    destination = directory / f"audio-{digest}.{extension}"
    if destination.is_file() and destination.stat().st_size:
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-y", "-i", str(source),
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
        "-c:a", "flac" if compress else "copy", "-f", container, str(partial),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode or not partial.is_file() or not partial.stat().st_size:
            raise ValueError(f"Cannot prepare audio from {source.name}: {result.stderr.strip()[-1000:]}")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    LOGGER.info("Audio upload: %.1f MiB from %.1f MiB source", destination.stat().st_size / 1024 ** 2,
                source.stat().st_size / 1024 ** 2)
    return destination

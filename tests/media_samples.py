"""Small real media for bundle tests, generated once per container format."""

import subprocess
from functools import cache
from pathlib import Path

import imageio_ffmpeg


@cache
def _sample(suffix: str) -> bytes:
    codec, container = {".flac": ("flac", "flac"), ".webm": ("libopus", "webm")}.get(
        suffix, ("pcm_s16le", "wav"))
    return subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=0.1", "-c:a", codec, "-f", container, "-"],
        capture_output=True, check=True,
    ).stdout


def write_audio(path: Path) -> None:
    """Write a decodable synthetic recording instead of placeholder bytes."""
    path.write_bytes(_sample(path.suffix))

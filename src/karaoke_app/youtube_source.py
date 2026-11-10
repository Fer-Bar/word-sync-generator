"""Acquire YouTube media for CLI and notebook workflows."""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from karaoke_app.terminal import failure_summary, notify, stream_process

LOGGER = logging.getLogger(__name__)


def is_youtube_url(value: str) -> bool:
    """Recognize YouTube hosts without accepting lookalike domains."""
    host = (urlparse(value).hostname or "").lower()
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def download_youtube(
    url: str, directory: Path, cookies: Path | None = None, *, video: bool = False,
) -> tuple[Path, dict]:
    """Download media, retrying with supplied cookies only when necessary."""
    if not shutil.which("deno"):
        raise RuntimeError("YouTube download requires Deno locally. Install https://deno.com/ and retry.")
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "yt_dlp", "--no-config", "--no-playlist",
        "--remote-components", "ejs:github", "--js-runtimes", "deno",
        "--write-info-json", "-f",
        "bv*[height<=720]+ba/b[height<=720]" if video else "bestaudio/best",
        "--output", str(directory / "source.%(ext)s"),
        "--print", "before_dl:KARAOKE_VIDEO %(.{title,artist,uploader,duration})j",
        "--print", "after_move:KARAOKE_FILE %(filepath)j", "--no-simulate", "--newline", "--progress",
        "--progress-delta", "0.5", "--progress-template", "download:KARAOKE_DOWNLOAD %(progress)j",
    ]
    if video:
        command.extend(["--merge-output-format", "mp4", "--remux-video", "mp4"])
    media_label = "video" if video else "audio"
    stage = f"download_{media_label}"
    notify("Finding YouTube video", stage="youtube")
    downloaded = []

    def on_line(line):
        prefix, _, payload = line.strip().partition(" ")
        if prefix not in {"KARAOKE_VIDEO", "KARAOKE_DOWNLOAD", "KARAOKE_FILE"}:
            return
        try:
            value = json.loads(payload)
        except ValueError:
            return
        if prefix == "KARAOKE_FILE" and isinstance(value, str):
            downloaded.append(Path(value))
        elif prefix == "KARAOKE_VIDEO" and isinstance(value, dict):
            values = {"Video": value.get("title"), "Artist": value.get("artist"),
                      "Channel": value.get("uploader")}
            duration = value.get("duration")
            if isinstance(duration, (int, float)):
                values["Duration"] = f"{int(duration) // 60}:{int(duration) % 60:02d}"
            LOGGER.info("Video found", extra={"user_event": {"kind": "metadata", "values": values}})
            notify("Finding YouTube video", stage="youtube", state="done")
        elif prefix == "KARAOKE_DOWNLOAD" and isinstance(value, dict):
            speed, eta = value.get("speed"), value.get("eta")
            details = []
            if isinstance(speed, (int, float)):
                details.append(f"{speed / 1024 ** 2:.1f} MB/s")
            if isinstance(eta, (int, float)):
                details.append(f"{int(eta)}s left")
            notify(f"Downloading {media_label}", stage=stage, completed=value.get("downloaded_bytes", 0),
                   total=value.get("total_bytes") or value.get("total_bytes_estimate"),
                   detail=" · ".join(details), unit="bytes")

    try:
        result = stream_process([*command, url], timeout=600, on_line=on_line)
        if result.returncode and cookies:
            notify("Download attempt failed. Retrying with local cookies.")
            notify(f"Downloading {media_label}", stage=stage, reset=True)
            result = stream_process([*command, "--cookies", str(cookies), url], timeout=600, on_line=on_line)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("YouTube download timed out. Retry the source command.") from error
    if result.returncode:
        cause = failure_summary(result.stdout, result.stderr)
        raise RuntimeError(f"YouTube download failed. {cause}")
    path = downloaded[-1] if downloaded else directory / "missing"
    if not path.is_file() or not path.stat().st_size:
        raise RuntimeError("YouTube did not produce a usable local audio file")
    raw = json.loads(path.with_suffix(".info.json").read_text(encoding="utf-8"))
    notify(f"Downloading {media_label}", stage=stage, state="done",
           completed=path.stat().st_size, total=path.stat().st_size)
    notify(f"{media_label.title()} ready · {path.stat().st_size / 1024 ** 2:.1f} MB")
    keys = ("title", "track", "artist", "creator", "uploader", "album", "language", "duration", "webpage_url")
    return path, {key: raw.get(key) for key in keys}

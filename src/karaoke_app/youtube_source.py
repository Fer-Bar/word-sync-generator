"""Acquire YouTube audio before provisioning a Colab runtime."""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)


def is_youtube_url(value: str) -> bool:
    """Recognize YouTube hosts without accepting lookalike domains."""
    host = (urlparse(value).hostname or "").lower()
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def download_youtube(url: str, directory: Path, cookies: Path | None = None) -> tuple[Path, dict]:
    """Download audio locally, retrying with supplied cookies only when necessary."""
    if not shutil.which("deno"):
        raise RuntimeError("YouTube download requires Deno locally. Install https://deno.com/ and retry.")
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "yt_dlp", "--no-config", "--no-playlist",
        "--remote-components", "ejs:github", "--js-runtimes", "deno",
        "--write-info-json", "-f", "bestaudio/best", "--output", str(directory / "source.%(ext)s"),
        "--print", "after_move:filepath", "--no-simulate",
    ]
    LOGGER.info("Downloading YouTube audio locally before starting Colab")
    try:
        result = subprocess.run([*command, url], capture_output=True, text=True, timeout=600)
        if result.returncode and cookies:
            LOGGER.info("Anonymous YouTube download failed; retrying locally with cookies")
            result = subprocess.run(
                [*command, "--cookies", str(cookies), url], capture_output=True, text=True, timeout=600,
            )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Local YouTube download timed out; no Colab session started") from error
    if result.returncode:
        raise RuntimeError(f"Local YouTube download failed; no Colab session started:\n{result.stderr.strip()}")
    lines = result.stdout.strip().splitlines()
    path = Path(lines[-1]) if lines else directory / "missing"
    if not path.is_file() or not path.stat().st_size:
        raise RuntimeError("YouTube did not produce a usable local audio file")
    raw = json.loads(path.with_suffix(".info.json").read_text(encoding="utf-8"))
    keys = ("title", "track", "artist", "creator", "uploader", "album", "language", "duration", "webpage_url")
    return path, {key: raw.get(key) for key in keys}

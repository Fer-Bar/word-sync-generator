"""Acquire notebook inputs using the same YouTube downloader as the CLI."""

import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from karaoke_app.notebook_inputs import validate_inputs
from karaoke_app.song_identity import resolve_song_identity
from karaoke_app.youtube_source import download_youtube, is_youtube_url


def acquire_youtube(url: str, directory: Path, cookies: Path | None = None) -> dict:
    """Download one video and suggest editable musical metadata without retaining cookies."""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not is_youtube_url(url):
        raise ValueError("Enter a YouTube video URL.")
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname.lower() == "youtu.be":
        video_id = parts[0]
    elif parts == ["watch"]:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
        video_id = parts[1]
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Use a single YouTube video URL, not a playlist or channel.")
    url = f"https://www.youtube.com/watch?v={video_id}"
    root = directory.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="karaoke-youtube-cookies-") as private:
        local_cookies = None
        if cookies is not None:
            local_cookies = Path(private) / "cookies.txt"
            shutil.copyfile(cookies, local_cookies)
            local_cookies.chmod(0o600)
        source, raw = download_youtube(url, root, local_cookies, video=True)
    selection = validate_inputs([source])
    identity = resolve_song_identity(raw, {})
    metadata = {key: identity.get(key) or raw.get(key) or selection["metadata"].get(key)
                for key in ("title", "track", "artist", "album", "video_title", "duration", "uploader")}
    metadata["webpage_url"] = url
    result = {**selection, "metadata": metadata, "origin": {"kind": "youtube", "url": url}}
    # Keep only the metadata needed by the form, not signed media URLs from yt-dlp.
    source.with_suffix(".info.json").unlink(missing_ok=True)
    return result

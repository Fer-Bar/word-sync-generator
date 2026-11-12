"""Resolve musical metadata independently of downloading, models or runtime paths."""

import logging
import re
from typing import Any


def _clean_music_title(value: str) -> str:
    """Remove presentation labels while retaining remix, live and edition markers."""
    label = (r"(?:official\s+(?:music\s+)?(?:audio|video|lyric\s+video)"
             r"|lyrics?(?:\s+video)?|audio\s+oficial|video\s+oficial)")
    value = re.sub(rf"\s*[\[(]\s*{label}\s*[\])]", "", value, flags=re.IGNORECASE)
    return value.strip().strip('\"“”').strip()


def _split_featured_artist(value: str) -> tuple[str, str | None]:
    match = re.search(r"\s+[\[(]?(?:feat\.?|ft\.?|featuring)\s+(.+?)\s*[\])]?$", value, re.IGNORECASE)
    if match:
        return value[:match.start()].strip(), match.group(1).strip()
    return value, None


def resolve_song_identity(
    raw: dict[str, Any], overrides: dict[str, Any], *, logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Prefer explicit values to conservative title inference, preserving edition names."""
    logger = logger if logger is not None else logging.getLogger(__name__)
    video_title = raw.get("video_title") or raw.get("title") or "karaoke"
    track = overrides.get("title") or raw.get("track")
    artist = overrides.get("artist") or raw.get("artist") or raw.get("creator")
    title = _clean_music_title(video_title)
    parts = re.split(r"\s+[-–—|]\s+", title)
    inferred_artist = inferred_track = None
    if len(parts) == 2 and all(parts):
        left, right = parts
        left_artist, _ = _split_featured_artist(left)
        right_artist, _ = _split_featured_artist(right)
        known_artist = str(artist).casefold() if artist else None
        known_track = _clean_music_title(str(track)).casefold() if track else None
        if known_artist and known_artist == right_artist.casefold():
            inferred_artist, inferred_track = right, left
        elif known_artist and known_artist != left_artist.casefold():
            logger.debug("Title inference skipped: video title conflicts with supplied artist=%r", artist)
        elif known_track and known_track == left.casefold():
            inferred_artist, inferred_track = right, left
        elif known_track and known_track != _split_featured_artist(right)[0].casefold():
            logger.debug("Title inference skipped: video title conflicts with supplied track=%r", track)
        else:
            inferred_artist, inferred_track = left, right
    elif len(parts) == 1:
        uploader = raw.get("uploader") or ""
        topic = re.fullmatch(r"(.+) - Topic", uploader, flags=re.IGNORECASE)
        if artist or topic:
            inferred_artist = artist or topic.group(1)
            inferred_track = title
    if inferred_track:
        inferred_track, featured = _split_featured_artist(inferred_track)
        if featured:
            inferred_artist = f"{inferred_artist} feat. {featured}"
        if not artist:
            artist = inferred_artist
            logger.debug("Artist inferred from video title/Topic channel: %r", artist)
        if not track:
            track = inferred_track
            logger.debug("Song name inferred from video title: %r", track)
    if not track:
        track = video_title
        logger.debug("Song name unavailable: no track or unambiguous title inference; using video title=%r. "
                     "Use --title to specify the song name.", video_title)
    if not artist:
        logger.debug("Artist unavailable: no artist/creator or unambiguous title inference; uploader=%r. "
                     "Use --artist to specify the artist.", raw.get("uploader"))
    logger.debug("Resolved song: track=%r artist=%r", track, artist)
    return {"title": track, "track": track, "artist": artist, "video_title": video_title}

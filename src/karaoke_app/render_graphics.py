"""Generate fresh thumbnails and transparent intro cards from a render job."""

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from karaoke_app.branding import THUMBNAIL_LOGO
from karaoke_app.job_document import resolve_job_asset, resolve_watermark_path
from karaoke_app.thumbnail import add_thumbnail_logo, create_title_overlay

LOGGER = logging.getLogger(__name__)


def graphic_metadata(document: dict[str, Any]) -> tuple[str, str | None]:
    """Resolve shared text, respecting explicit intro overrides."""
    intro = document.get("intro") or {}
    artist = (
        intro.get("artist") or document.get("source", {}).get("artist") or document.get("metadata", {}).get("artist")
    )
    if artist is not None and not isinstance(artist, str):
        raise ValueError("Artist must be text in intro.artist, source.artist or metadata.artist")
    return intro.get("title") or document["title"], artist


def graphic_logo(job_dir: Path, document: dict[str, Any]) -> Path | None:
    """Use the configured branding, including an explicit decision to disable it."""
    watermark = document.get("watermark") or {}
    if watermark.get("enabled") is False:
        return None
    if watermark.get("path"):
        return resolve_watermark_path(job_dir, watermark["path"])
    reference = THUMBNAIL_LOGO
    return reference if reference.is_file() else None


def background_frame(job_dir: Path, document: dict[str, Any]) -> Image.Image:
    """Render time zero with the same dimensions, seed and dimming as the video."""
    video, background = document["video"], document["background"]
    size = (video["width"], video["height"])
    if background["kind"] == "cosmic":
        from karaoke_app.cosmic_background import CosmicBackground

        return CosmicBackground(background, *size).frame(0)
    if background["kind"] == "solid":
        return Image.new("RGB", size, background["color"])
    path = resolve_job_asset(job_dir, background["path"], "background")
    with Image.open(path) as image:
        frame = ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    # FFmpeg's drawbox uses the opacity rounded to two decimal places.
    return ImageEnhance.Brightness(frame).enhance(1 - round(background.get("overlay_opacity", 0), 2))


def intro_timing(document: dict[str, Any], transcript: dict[str, Any] | None) -> dict[str, Any] | None:
    """End the card before the earliest vocal, including overlapping/background voices."""
    config = document.get("intro") or {}
    if config.get("enabled") is False:
        return None
    starts = []
    for segment in (transcript or {}).get("segments", []):
        words = segment.get("words") or []
        starts.extend(word["start"] for word in words)
        if not words and "start" in segment:
            starts.append(segment["start"])
    if not starts:
        return None
    start = float(config.get("start", 0))
    end = min(start + float(config.get("duration", 5)), float(config.get("end", float("inf"))), min(starts) - 0.8)
    if end - start < 1 / document["video"]["fps"]:
        return None
    return {**config, "enabled": True, "start": start, "end": end, "duration": end - start}


def generate_render_graphics(
    job_dir: Path,
    document: dict[str, Any],
    modes: tuple[str, ...],
    destination: Path,
    transcript: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Write mode-specific PNGs without modifying the job or reusing stale intro files."""
    title, artist = graphic_metadata(document)
    if not artist:
        LOGGER.warning("No artist metadata found; render graphics will show only the song title")
    logo = graphic_logo(job_dir, document)
    frame = background_frame(job_dir, document)
    destination.mkdir(parents=True, exist_ok=True)
    frame.save(destination / "background.png")
    timing = intro_timing(document, transcript)
    for mode in modes:
        overlay = create_title_overlay(title, artist, mode=mode, size=frame.size)
        thumbnail = Image.alpha_composite(frame.convert("RGBA"), overlay)
        if logo is not None:
            add_thumbnail_logo(thumbnail, logo)
        thumbnail = thumbnail.convert("RGB")
        thumbnails = destination / "thumbnails"
        thumbnails.mkdir(exist_ok=True)
        thumbnail.resize((1280, 720), Image.Resampling.LANCZOS).save(thumbnails / f"thumbnail_{mode}.png")
        if timing:
            intros = destination / "intro"
            intros.mkdir(exist_ok=True)
            overlay.save(intros / f"intro_{mode}.png")
    LOGGER.info(
        "Generated thumbnails for %s; instrumental intro %s", ", ".join(modes), "enabled" if timing else "omitted"
    )
    return timing

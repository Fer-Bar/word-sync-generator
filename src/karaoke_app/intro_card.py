"""Transparent intro titles sharing the thumbnail design, without embedded branding."""

from pathlib import Path

from karaoke_app.thumbnail import create_title_overlay


def create_intro_card(
    title: str,
    artist: str | None = None,
    *,
    width: int = 1920,
    height: int = 1080,
    output_path: Path,
    mode: str = "lyrics",
) -> Path:
    """Save an unbranded RGBA title card; the renderer adds the video watermark."""
    overlay = create_title_overlay(title, artist, mode=mode, size=(width, height))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(output_path)
    return output_path


def generate_intro_card_for_job(
    job_dir: Path,
    output_filename: str = "intro_card.png",
    *,
    mode: str = "lyrics",
) -> Path | None:
    """Generate a fresh intro from the job metadata unless explicitly disabled."""
    from karaoke_app.job_document import load_job_document
    from karaoke_app.render_graphics import graphic_metadata

    root = job_dir.expanduser().resolve()
    document = load_job_document(root)
    if (document.get("intro") or {}).get("enabled") is False:
        return None
    title, artist = graphic_metadata(document)
    video = document["video"]
    return create_intro_card(
        title,
        artist,
        mode=mode,
        width=video["width"],
        height=video["height"],
        output_path=root / output_filename,
    )

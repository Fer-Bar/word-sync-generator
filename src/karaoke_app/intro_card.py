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
    align: str = "start",
    graphic_style: str = "default",
    graphic_palette: str = "light",
    title_layout: str = "stacked",
) -> Path:
    """Save an unbranded RGBA title card; the renderer adds the video watermark."""
    overlay = create_title_overlay(title, artist, mode=mode, align=align, size=(width, height),
                                   graphic_style=graphic_style,
                                   graphic_palette=graphic_palette, title_layout=title_layout)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(output_path)
    return output_path


def generate_intro_card_for_job(
    job_dir: Path,
    output_filename: str = "intro_card.png",
    *,
    mode: str = "lyrics",
    align: str | None = None,
    graphic_style: str | None = None,
    graphic_palette: str | None = None,
    title_layout: str | None = None,
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
        align=align if align is not None else (document.get("intro") or {}).get("align", "start"),
        graphic_style=graphic_style or (document.get("intro") or {}).get("graphic_style", "default"),
        graphic_palette=graphic_palette or (document.get("intro") or {}).get("graphic_palette", "light"),
        title_layout=title_layout or (document.get("intro") or {}).get("title_layout", "stacked"),
        width=video["width"],
        height=video["height"],
        output_path=root / output_filename,
    )

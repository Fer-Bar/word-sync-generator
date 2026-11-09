"""Local, deterministic thumbnail composition based on the thumbnails references."""

import argparse
import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from karaoke_app.branding import THUMBNAIL_LOGO
from karaoke_app.resources import PROJECT_ROOT

FONTS = Path(__file__).parent / "assets" / "fonts"
REFERENCES = PROJECT_ROOT / "references" / "thumbnails"
SIZE = (1672, 941)


def _font(path: Path, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size)
    if weight is not None and path == FONTS / "Montserrat.ttf":
        font.set_variation_by_axes([weight])
    return font


def _text_mask(text: str, font: ImageFont.FreeTypeFont, tracking: int = 0) -> Image.Image:
    widths = [font.getlength(char) for char in text]
    box = font.getbbox(text)
    mask = Image.new("L", (max(1, int(sum(widths) + tracking * len(text) + 20)), box[3] - box[1] + 20))
    draw = ImageDraw.Draw(mask)
    if tracking:
        x = 10.0
        for char, width in zip(text, widths, strict=True):
            draw.text((x, 10 - box[1]), char, font=font, fill=255)
            x += width + tracking
    else:
        draw.text((10 - box[0], 10 - box[1]), text, font=font, fill=255)
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError("Text must contain visible characters")
    return mask.crop(bounds)


def _title_mask(title: str, font_path: Path) -> Image.Image:
    font = _font(font_path, 440)
    lines = title.upper().splitlines()
    if len(lines) > 2:
        raise ValueError("Title supports at most two lines")
    if len(lines) == 1:
        words = title.upper().split()
        original = _text_mask(lines[0], font)
        if original.width / original.height > 5 and len(words) > 1:
            split = min(
                range(1, len(words)),
                key=lambda i: max(font.getlength(" ".join(words[:i])), font.getlength(" ".join(words[i:]))),
            )
            lines = [" ".join(words[:split]), " ".join(words[split:])]
    masks = [_text_mask(line, font) for line in lines]
    gap = 20
    mask = Image.new("L", (max(m.width for m in masks), sum(m.height for m in masks) + gap * (len(masks) - 1)))
    y = 0
    for line in masks:
        mask.paste(line, ((mask.width - line.width) // 2, y))
        y += line.height + gap
    # Short titles retain the tall, condensed proportions of the reference.
    height = 344
    width = min(1100, round(mask.width * height / mask.height))
    return mask.resize((width, height), Image.Resampling.LANCZOS)


def _paint_text(canvas: Image.Image, mask: Image.Image, position: tuple[int, int], *, texture: bool) -> None:
    layer = Image.new("L", SIZE)
    layer.paste(mask, position)
    shadow = Image.new("RGBA", SIZE, (0, 0, 0, 235))
    shifted = Image.new("L", SIZE)
    shifted.paste(layer, (5, 12))
    shadow.putalpha(shifted.filter(ImageFilter.GaussianBlur(13)))
    canvas.alpha_composite(shadow)
    ink = Image.new("RGBA", SIZE, (255, 252, 241, 255))
    if texture:
        rng = np.random.default_rng(17)
        grain = rng.normal(0, 0.9, (SIZE[1], SIZE[0], 1))
        pixels = np.clip(np.array([255, 251, 239]) + grain, 0, 255).astype(np.uint8)
        ink = Image.fromarray(pixels).convert("RGBA")
        draw = ImageDraw.Draw(ink)
        for _ in range(1600):
            x, y = int(rng.integers(SIZE[0])), int(rng.integers(SIZE[1]))
            draw.line(
                [(x, y), (x + int(rng.integers(-6, 7)), y + int(rng.integers(2, 10)))], fill=(240, 229, 206), width=1
            )
    ink.putalpha(layer)
    canvas.alpha_composite(ink)


def _lyrics_overlay(title: str, artist: str | None, title_font: Path, artist_font: Path, align: str) -> Image.Image:
    """Compose an aligned music cover with a localized transparent scrim."""
    lines = title.strip().upper().splitlines()
    if len(lines) > 2 or any(not line.strip() for line in lines):
        raise ValueError("Title supports at most two non-empty lines")
    font = _font(title_font, 260, 900)
    max_width = round(SIZE[0] * 0.70)
    if len(lines) == 1 and font.getlength(lines[0]) > max_width:
        words = lines[0].split()
        if len(words) > 1:
            split = min(range(1, len(words)), key=lambda i: max(
                font.getlength(" ".join(words[:i])), font.getlength(" ".join(words[i:]))))
            lines = [" ".join(words[:split]), " ".join(words[split:])]
    masks = [_text_mask(line.strip(), font) for line in lines]
    scale = min(1, max_width / max(mask.width for mask in masks))
    masks = [mask.resize((max(1, round(mask.width * scale)), max(1, round(mask.height * scale))),
                         Image.Resampling.LANCZOS) for mask in masks]
    gap = max(8, round(30 * scale))
    artist_mask = None
    if artist and artist.strip():
        artist_mask = _text_mask(" ".join(artist.split()), _font(artist_font, max(1, round(70 * scale)), 700))
        artist_scale = min(1, max_width / artist_mask.width)
        artist_mask = artist_mask.resize((max(1, round(artist_mask.width * artist_scale)),
                                         max(1, round(artist_mask.height * artist_scale))), Image.Resampling.LANCZOS)
    height = sum(mask.height for mask in masks) + gap * (len(masks) - 1)
    if artist_mask is not None:
        height += 38 + artist_mask.height
    margin, top = round(SIZE[0] * .08), (SIZE[1] - height) // 2

    def text_x(width: int) -> int:
        if align == "center":
            return (SIZE[0] - width) // 2
        return margin if align == "start" else SIZE[0] - margin - width
    yy, xx = np.mgrid[:SIZE[1], :SIZE[0]]
    horizontal = np.clip(1 - xx / (SIZE[0] * .88), 0, 1)
    if align == "end":
        horizontal = horizontal[:, ::-1]
    elif align == "center":
        horizontal = np.clip(1 - abs(xx - SIZE[0] / 2) / (SIZE[0] * .5), 0, 1)
    vertical = np.clip(1 - np.maximum(top - yy, yy - (top + height)) / 120, 0, 1)
    canvas = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    canvas.putalpha(Image.fromarray((horizontal * vertical * 145).astype(np.uint8)))
    text_layer = Image.new("L", SIZE)
    y = top
    for mask in masks:
        text_layer.paste(mask, (text_x(mask.width), y))
        y += mask.height + gap
    if artist_mask is not None:
        text_layer.paste(artist_mask, (text_x(artist_mask.width), top + height - artist_mask.height))
    shadow_mask = Image.new("L", SIZE)
    shadow_mask.paste(text_layer, (2, 3))
    shadow = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    shadow.putalpha(shadow_mask.filter(ImageFilter.GaussianBlur(5)))
    canvas.alpha_composite(shadow)
    ink = Image.new("RGBA", SIZE, (255, 252, 245, 0))
    ink.putalpha(text_layer)
    canvas.alpha_composite(ink)
    return canvas


def create_title_overlay(
    title: str,
    artist: str | None,
    *,
    mode: str = "lyrics",
    align: str = "start",
    graphic_style: str = "default",
    logo_path: Path | None = None,
    title_font: Path | None = None,
    artist_font: Path = FONTS / "Montserrat.ttf",
    size: tuple[int, int] = SIZE,
    texture: bool = True,
) -> Image.Image:
    """Draw the shared thumbnail/intro design on a transparent canvas."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Title must be non-empty text")
    if align not in ("start", "center", "end"):
        raise ValueError("Align must be start, center or end")
    if mode not in {"lyrics", "karaoke"}:
        raise ValueError("Mode must be lyrics or karaoke")
    if graphic_style != "default":
        raise ValueError("Unknown graphic style")
    title_font = title_font or FONTS / ("BarlowCondensed-BlackItalic.ttf" if mode == "lyrics" else "Anton-Regular.ttf")
    if mode == "lyrics":
        canvas = _lyrics_overlay(title, artist, title_font, artist_font, align)
        if logo_path is not None:
            add_thumbnail_logo(canvas, logo_path)
        return canvas.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", SIZE)
    if artist and artist.strip():
        artist_mask = _text_mask(" ".join(artist.upper().split()), _font(artist_font, 128, 900))
        scale = min(1100 / artist_mask.width, 94 / artist_mask.height)
        artist_mask = artist_mask.resize(
            (max(1, round(artist_mask.width * scale)), max(1, round(artist_mask.height * scale))),
            Image.Resampling.LANCZOS,
        )
        _paint_text(
            canvas, artist_mask, ((SIZE[0] - artist_mask.width) // 2, 288 - artist_mask.height), texture=texture
        )
    title_mask = _title_mask(title.strip(), title_font)
    _paint_text(canvas, title_mask, ((SIZE[0] - title_mask.width) // 2, 314), texture=texture)
    label = _text_mask(mode.upper(), _font(FONTS / "Montserrat.ttf", 53, 700), tracking=18)
    _paint_text(canvas, label, ((SIZE[0] - label.width) // 2, 699), texture=False)
    draw = ImageDraw.Draw(canvas)
    left = (SIZE[0] - label.width) // 2
    for start, end in [(left - 246, left - 42), (left + label.width + 42, left + label.width + 246)]:
        draw.line((start, 717, end, 717), fill=(255, 252, 245), width=6)
    if logo_path is not None:
        add_thumbnail_logo(canvas, logo_path)
    return canvas.resize(size, Image.Resampling.LANCZOS)


def add_thumbnail_logo(canvas: Image.Image, logo_path: Path) -> None:
    """Composite the thumbnail logo in the lower left, scaled to the canvas."""
    layer = Image.new("RGBA", SIZE)
    with Image.open(logo_path) as source:
        logo = source.convert("RGBA")
    bounds = logo.getchannel("A").point(lambda v: 255 if v > 220 else 0).getbbox()
    if bounds is None:
        raise ValueError("Logo is fully transparent")
    logo = logo.crop(bounds)
    logo.thumbnail((270, 80), Image.Resampling.LANCZOS)
    layer.alpha_composite(logo, (40, 892 - logo.height))
    canvas.alpha_composite(layer.resize(canvas.size, Image.Resampling.LANCZOS))


def create_thumbnail(
    title: str,
    artist: str,
    output_path: Path,
    *,
    mode: str = "lyrics",
    align: str = "start",
    graphic_style: str = "default",
    background_path: Path | Image.Image = REFERENCES / "background.png",
    logo_path: Path | None = THUMBNAIL_LOGO,
    title_font: Path | None = None,
    artist_font: Path = FONTS / "Montserrat.ttf",
    width: int = 1280,
    texture: bool = True,
) -> Path:
    """Render an RGB 16:9 PNG with dynamic text and the supplied reference assets."""
    if not isinstance(title, str) or not title.strip() or not isinstance(artist, str) or not artist.strip():
        raise ValueError("Title and artist must be non-empty text")
    if len(title) > 200 or len(artist) > 200:
        raise ValueError("Title and artist must each contain at most 200 characters")
    if align not in ("start", "center", "end"):
        raise ValueError("Align must be start, center or end")
    if mode not in {"lyrics", "karaoke"}:
        raise ValueError("Mode must be lyrics or karaoke")
    if isinstance(width, bool) or not isinstance(width, int) or width < 640 or width > 3840 or width % 16:
        raise ValueError("Width must be a multiple of 16 between 640 and 3840")
    output_path = Path(output_path)
    title_font = title_font or FONTS / ("BarlowCondensed-BlackItalic.ttf" if mode == "lyrics" else "Anton-Regular.ttf")
    inputs = [title_font, artist_font, *([logo_path] if logo_path else [])]
    if isinstance(background_path, (str, Path)):
        inputs.append(Path(background_path))
    if output_path.resolve() in {Path(p).resolve() for p in inputs}:
        raise ValueError("Output must not overwrite a source asset")
    if output_path.suffix.lower() != ".png":
        raise ValueError("Thumbnail output must have a .png extension")
    if isinstance(background_path, Image.Image):
        canvas = ImageOps.fit(background_path.convert("RGBA"), SIZE, method=Image.Resampling.LANCZOS)
    else:
        with Image.open(background_path) as source:
            canvas = ImageOps.fit(source.convert("RGBA"), SIZE, method=Image.Resampling.LANCZOS)
    canvas.alpha_composite(
        create_title_overlay(
            title,
            artist,
            mode=mode,
            align=align,
            graphic_style=graphic_style,
            logo_path=logo_path,
            title_font=title_font,
            artist_font=artist_font,
            texture=texture,
        )
    )
    result = canvas.convert("RGB").resize((width, width * 9 // 16), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path, format="PNG", optimize=True)
    return output_path


def run_thumbnail(argv: list[str]) -> None:
    """Parse the independent thumbnail command and optionally read job metadata."""
    from karaoke_app.themes import THEMES, apply_render_theme
    from karaoke_app.visual_config import BACKGROUND_STYLES

    parser = argparse.ArgumentParser(prog="karaoke thumbnail", description=__doc__)
    parser.add_argument("job_dir", nargs="?", type=Path)
    parser.add_argument("--align", choices=("start", "center", "end"), help="Lyrics title and artist alignment")
    parser.add_argument("--graphic-style", choices=("default",))
    parser.add_argument("--title")
    parser.add_argument("--artist")
    parser.add_argument("--mode", choices=("lyrics", "karaoke", "both"), default="both")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--background", type=Path, default=None)
    parser.add_argument("--background-style", choices=BACKGROUND_STYLES)
    parser.add_argument("--theme", choices=tuple(THEMES.keys()), help="Preset color palette")
    parser.add_argument("--cover", type=Path, help="Artwork palette for procedural background")
    parser.add_argument("--logo", type=Path, help="Override the project logo")
    parser.add_argument("--no-logo", action="store_true")
    parser.add_argument(
        "--title-font", type=Path,
        help="Title font (default: Barlow Condensed Black Italic for lyrics, Anton for karaoke)"
    )
    parser.add_argument("--artist-font", type=Path, default=FONTS / "Montserrat.ttf")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--no-texture", action="store_true")
    args = parser.parse_args(argv)
    title, artist = args.title, args.artist
    doc = None
    if args.job_dir:
        from karaoke_app.job_document import load_job_document

        doc = load_job_document(args.job_dir)
        title = title if title is not None else doc.get("title")
        artist = (
            artist
            if artist is not None
            else (doc.get("intro", {}).get("artist") or doc.get("source", {}).get("artist")
                  or doc.get("metadata", {}).get("artist"))
        )
    if not title or not artist:
        raise ValueError("Supply --title and --artist, or configure the project title and artist first")
    from karaoke_app.cli import _safe_filename

    output_dir = args.output_dir or (
        args.job_dir / "thumbnails"
        if args.job_dir
        else Path("outputs/thumbnails") / _safe_filename(f"{artist}-{title}")
    )

    bg: Path | Image.Image
    if args.background is not None:
        bg = args.background
    else:
        from karaoke_app.render_graphics import background_frame
        from karaoke_app.visual_config import apply_visual_options

        target_doc = doc if doc is not None else {
            "video": {"width": 1920, "height": 1080, "fps": 24},
            "background": {"kind": "solid", "color": "#0B1020"},
        }
        if "video" not in target_doc:
            target_doc["video"] = {"width": 1920, "height": 1080, "fps": 24}
        if args.background_style or args.cover:
            target_doc = apply_visual_options(
                target_doc,
                background_style=args.background_style,
                cover=args.cover,
            )
        if args.theme:
            target_doc, _ = apply_render_theme(target_doc, theme=args.theme)
        job_root = args.job_dir or Path(".")
        bg = background_frame(job_root, target_doc, time=target_doc.get("thumbnail", {}).get("time", 0))

    from karaoke_app.render_graphics import graphic_logo

    intro = (doc or {}).get("intro") or {}
    thumbnail = (doc or {}).get("thumbnail") or {}
    align = args.align if args.align is not None else thumbnail.get("align", intro.get("align", "start"))
    logo = None if args.no_logo else args.logo
    if logo is None and not args.no_logo:
        logo = graphic_logo(args.job_dir or Path("."), doc or {})
    graphic_style = args.graphic_style or ((doc or {}).get("intro") or {}).get("graphic_style", "default")
    for mode in ("lyrics", "karaoke") if args.mode == "both" else (args.mode,):
        output = create_thumbnail(
            title,
            artist,
            output_dir / f"thumbnail_{mode}.png",
            mode=mode,
            align=align,
            graphic_style=graphic_style,
            background_path=bg,
            logo_path=logo,
            title_font=args.title_font,
            artist_font=args.artist_font,
            width=args.width,
            texture=not args.no_texture,
        )
        logging.getLogger(__name__).info("Thumbnail created: %s", output)

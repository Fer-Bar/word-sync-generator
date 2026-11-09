"""Clean FOMO title compositions with adaptive rows and shared intro geometry."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

GRAPHIC_STYLES = ("default", "fomo", "fomo-xerox")
GRAPHIC_PALETTES = ("light", "dark")
TITLE_LAYOUTS = ("stacked", "wide")


def title_rows(title: str, layout: str) -> list[str]:
    """Respect explicit breaks; otherwise balance arbitrary titles into at most four rows."""
    if layout not in TITLE_LAYOUTS:
        raise ValueError("Title layout must be stacked or wide")
    lines = title.strip().upper().splitlines()
    if not lines or len(title) > 200 or len(lines) > 4 or any(not line.strip() for line in lines):
        raise ValueError("FOMO title needs 1–200 characters and at most four non-empty lines")
    if len(lines) > 1:
        return [" ".join(line.split()) for line in lines]
    words = lines[0].split()
    count = min(len(words), 4 if layout == "stacked" else 2)
    rows = []
    for remaining in range(count, 0, -1):
        target = (sum(map(len, words)) + len(words) - remaining) / remaining
        take = 1
        while take < len(words) - remaining + 1:
            before = len(" ".join(words[:take]))
            after = len(" ".join(words[:take + 1]))
            if abs(after - target) >= abs(before - target):
                break
            take += 1
        rows.append(" ".join(words[:take]))
        words = words[take:]
    return rows


def create_fomo_overlay(title: str, artist: str | None, *, size: tuple[int, int], align: str,
                        layout: str = "stacked", title_font: Path | None = None,
                        xerox: bool = False, palette: str = "light") -> Image.Image:
    """Fit title rows into a safe area with the artist above and room for branding below."""
    from karaoke_app.thumbnail import FONTS, _font, _text_mask

    if align not in ("start", "center", "end"):
        raise ValueError("Align must be start, center or end")
    font = _font(title_font or FONTS / "AbrilFatface-Regular.ttf", 220)
    masks = [_text_mask(row, font) for row in title_rows(title, layout)]
    canvas = Image.new("RGBA", (1280, 720))
    max_width = 1040 if layout == "wide" else 860
    gap = 14
    height = min(420, 170 * len(masks))
    row_height = (height - gap * (len(masks) - 1)) // len(masks)
    top = 164 + (420 - height) // 2

    def x_for(width: int) -> int:
        return {"start": 80, "center": (1280 - width) // 2, "end": 1200 - width}[align]

    for mask in masks:
        natural_width = round(mask.width * row_height / mask.height)
        width = min(max_width, max(round(max_width * .72), natural_width))
        mask = mask.resize((width, row_height), Image.Resampling.LANCZOS)
        canvas.paste((10, 10, 10, 255), (x_for(width), top), mask)
        top += row_height + gap
    if artist and artist.strip():
        mask = _text_mask(" ".join(artist.upper().split()), _font(font.path, 46))
        scale = min(1, max_width / mask.width)
        mask = mask.resize((max(1, round(mask.width * scale)), max(1, round(mask.height * scale))),
                           Image.Resampling.LANCZOS)
        canvas.paste((10, 10, 10, 255), (x_for(mask.width), 80), mask)
    if xerox:
        canvas = xerox_ink(canvas)
    return apply_palette(canvas.resize(size, Image.Resampling.LANCZOS), palette)


def fomo_logo(logo_path: Path, *, palette: str = "light") -> Image.Image:
    """Return monochrome branding suitable for the white FOMO background."""
    with Image.open(logo_path) as source:
        logo = source.convert("RGBA")
    bounds = logo.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Logo is fully transparent")
    logo = logo.crop(bounds)
    alpha = logo.getchannel("A")
    logo = ImageOps.grayscale(logo).convert("RGBA")
    logo.putalpha(alpha)
    # Light lettering needs dark ink on white; keep opaque artwork intact.
    if logo.width > logo.height * 2:
        logo = ImageOps.invert(logo.convert("RGB")).convert("RGBA")
        logo.putalpha(alpha)
    return apply_palette(logo, palette)


def add_fomo_logo(canvas: Image.Image, logo_path: Path, *, align: str = "start", palette: str = "light") -> None:
    """Place branding in the footer reserved by every FOMO title composition."""
    logo = fomo_logo(logo_path, palette=palette)
    scale = canvas.width / 1280
    logo.thumbnail((round(180 * scale), round(52 * scale)), Image.Resampling.LANCZOS)
    x = {"start": round(80 * scale), "center": (canvas.width - logo.width) // 2,
         "end": canvas.width - round(80 * scale) - logo.width}[align]
    canvas.alpha_composite(logo, (x, round(630 * scale)))


def apply_graphic_options(document: dict, *, graphic_style: str | None = None,
                          title_layout: str | None = None, align: str | None = None,
                          graphic_palette: str | None = None) -> dict:
    """Apply explicitly chosen graphic defaults; preserve saved customizations on reload."""
    import copy

    result = copy.deepcopy(document)
    options = {
        "graphic_style": graphic_style, "title_layout": title_layout,
        "align": align, "graphic_palette": graphic_palette,
    }
    choices = {"graphic_style": GRAPHIC_STYLES, "title_layout": TITLE_LAYOUTS, "align": ("start", "center", "end"),
               "graphic_palette": GRAPHIC_PALETTES}
    for key, value in options.items():
        if value is not None:
            if value not in choices[key]:
                raise ValueError(f"Invalid {key}: {value}")
            result.setdefault("intro", {})[key] = value
    if ((graphic_style is not None or graphic_palette is not None)
            and (result.get("intro") or {}).get("graphic_style") in ("fomo", "fomo-xerox")):
        from karaoke_app.lyrics_plus import apply_plus_typography

        dark = (result.get("intro") or {}).get("graphic_palette", "light") == "dark"
        result["background"] = {"kind": "solid", "color": "#000000" if dark else "#FFFFFF"}
        watermark = result.get("watermark")
        if watermark and watermark.get("enabled", True):
            watermark.update({"position": "bottom_right" if (result.get("intro") or {}).get("align") == "end"
                              else "bottom_left", "scale": 0.06, "margin": 0.05})
        if not result.get("style"):
            apply_plus_typography(result)
        result["style"].update({
            "primary_color": "#EEEEEE" if dark else "#111111",
            "highlight_color": "#888888" if dark else "#777777",
            "coros_color": "#555555", "outline_width": 0, "shadow_depth": 0,
            "shadow_opacity": 0, "agent_colors": {},
            "lyrics_colors": {
                "active": "#EEEEEE" if dark else "#111111",
                "inactive": "#888888" if dark else "#777777",
            },
        })
    return result


def fomo_paper(size: tuple[int, int], *, xerox: bool = False, palette: str = "light") -> Image.Image:
    """Generate stable monochrome paper at a canonical resolution, without flickering grain."""
    if not xerox:
        return apply_palette(Image.new("RGB", size, "white"), palette)
    rng = np.random.default_rng(2718)
    cloud = Image.fromarray(rng.integers(0, 256, (36, 64), dtype=np.uint8)).resize(
        (1280, 720), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(9))
    grain = rng.normal(0, 2.8, (720, 1280))
    paper = 250 + grain + (np.asarray(cloud, dtype=float) - 128) * .035
    dust = rng.random((720, 1280)) < .003
    paper[dust] -= rng.uniform(15, 70, int(dust.sum()))
    paper_image = Image.fromarray(np.clip(paper, 0, 255).astype(np.uint8)).convert("RGB").resize(
        size, Image.Resampling.LANCZOS)
    return apply_palette(paper_image, palette)


def xerox_ink(canvas: Image.Image) -> Image.Image:
    """Distress letter edges and ink coverage while preserving transparent title margins."""
    rng = np.random.default_rng(31415)
    pixels = np.array(canvas)
    height, width = pixels.shape[:2]
    yy, xx = np.mgrid[:height, :width]
    displacement = rng.normal(0, .55, (height, width))
    shifted_x = np.clip(np.rint(xx + displacement).astype(int), 0, width - 1)
    shifted_y = np.clip(np.rint(yy + rng.normal(0, .4, (height, width))).astype(int), 0, height - 1)
    alpha = pixels[shifted_y, shifted_x, 3].astype(float)
    coverage = np.clip(rng.normal(.95, .065, (height, width)), .5, 1)
    pinholes = rng.random((height, width)) < .055
    coverage[pinholes] *= rng.uniform(.2, .65, int(pinholes.sum()))
    pixels[:, :, :3] = 16
    pixels[:, :, 3] = np.clip(alpha * coverage, 0, 255).astype(np.uint8)
    return Image.fromarray(pixels)


def apply_palette(image: Image.Image, palette: str) -> Image.Image:
    """Invert monochrome artwork without changing its transparency or texture geometry."""
    if palette not in GRAPHIC_PALETTES:
        raise ValueError("Graphic palette must be light or dark")
    if palette == "light":
        return image
    result = ImageOps.invert(image.convert("RGB"))
    if image.mode == "RGBA":
        result = result.convert("RGBA")
        result.putalpha(image.getchannel("A"))
    return result

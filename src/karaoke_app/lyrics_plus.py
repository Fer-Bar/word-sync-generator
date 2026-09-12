"""Even Better Lyrics Plus inspired video preset and locally cached typography."""

import io
import logging
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageFont

PRESET = "even-better-lyrics-plus"
FONT_DIRECTORY = Path.home() / ".cache" / "karaoke" / "fonts"


def switzer_font() -> Path:
    """Obtain an unmodified Switzer Semibold from Fontshare for this installation."""
    path = FONT_DIRECTORY / "Switzer-Semibold.otf"
    if path.is_file():
        ImageFont.truetype(str(path), 16)
        return path
    logging.getLogger(__name__).info("Downloading Switzer Semibold from Fontshare")
    with urllib.request.urlopen("https://api.fontshare.com/v2/fonts/download/switzer", timeout=60) as response:
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        font = archive.read("Switzer_Complete/Fonts/OTF/Switzer-Semibold.otf")
        license_text = archive.read("Switzer_Complete/License/FFL.txt")
    ImageFont.truetype(io.BytesIO(font), 16)
    FONT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (FONT_DIRECTORY / "Switzer-FFL.txt").write_bytes(license_text)
    path.write_bytes(font)
    return path


def cover_palette(path: Path) -> dict[str, str]:
    """Extract two dominant artwork colors deterministically, without uploading it."""
    with Image.open(path) as artwork:
        rgb = artwork.convert("RGB")
        rgb.thumbnail((128, 128))
        quantized = rgb.quantize(colors=8)
    palette = quantized.getpalette()
    colors = sorted(quantized.getcolors(), reverse=True)
    candidates = [tuple(palette[index * 3:index * 3 + 3]) for _, index in colors]
    visible = [color for color in candidates if max(color) > 35 and min(color) < 235] or candidates
    first = visible[0]
    second = max(visible, key=lambda color: sum((a - b) ** 2 for a, b in zip(color, first, strict=True)))
    return {key: '#' + ''.join(f'{channel:02X}' for channel in color)
            for key, color in (("color", first), ("secondary_color", second))}


def apply_plus_typography(document: dict[str, Any]) -> None:
    """Set shared Plus typography; render mode selects scrolling or fixed pages."""
    height = document.get("video", {}).get("height", 1080)
    document["style"] = {
        **(document.get("style") or {}), "lyrics_effect": "word-synced", "font_family": "Switzer Semibold",
        "font_size": max(12, round(height * 0.074)), "bold": False, "italic": False,
        "outline_width": 0, "shadow_depth": 1, "shadow_opacity": 0.25,
        "primary_color": "#FFFFFF", "highlight_color": "#A8A8A8", "agent_colors": {},
        "lyrics_colors": {"active": "#FFFFFF", "inactive": "#A8A8A8"},
        "margin_h": round(height * 0.12), "line_gap_factor": 1.5,
    }


def apply_lyrics_plus(document: dict[str, Any], cover: Path | None = None) -> None:
    """Apply Plus typography and the fluid background to a render copy."""
    apply_plus_typography(document)
    document["background"].update({
        "appearance": "fluid", "detail": 0, "overlay_opacity": 0.25,
        "brightness": 0.65, "contrast": 1, "base_color": "#08090C",
    })
    if cover is not None:
        document["background"].update(cover_palette(cover))

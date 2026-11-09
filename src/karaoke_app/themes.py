"""Named cosmic palettes resolved once for all outputs of a render."""

import copy
import secrets
from typing import Any

from karaoke_app.cosmic_background import normalize_cosmic_background
from karaoke_app.lyrics_plus import PRESET, apply_lyrics_plus

DEFAULT_THEME = "aurora"
THEMES = {
    "forest": {"color": "#123D29", "secondary_color": "#245C3E", "base_color": "#030A06"},
    "synthwave": {"color": "#7928CA", "secondary_color": "#00DFD8", "base_color": "#080711"},
    "sunset": {"color": "#B83B5E", "secondary_color": "#F9A826", "base_color": "#0D0709"},
    "aurora": {"color": "#1D4E89", "secondary_color": "#52B788", "base_color": "#040B0E"},
    "stellar": {"color": "#3F3F46", "secondary_color": "#CBD5E1", "base_color": "#050506"},
}


def apply_render_theme(
    document: dict[str, Any],
    theme: str = DEFAULT_THEME,
    seed: int | None = None,
) -> tuple[dict[str, Any], str]:
    """Return a themed copy, preserving explicit job backgrounds only with theme=job."""
    if theme not in {*THEMES, PRESET, "random", "job"}:
        raise ValueError(f"Unknown theme: {theme}")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2**32 - 1):
        raise ValueError("Seed must be an integer between 0 and 4294967295")
    result = copy.deepcopy(document)
    background = result["background"]
    if theme == "job":
        if seed is not None:
            if background["kind"] != "cosmic":
                raise ValueError("--seed requires a cosmic background when --theme job is selected")
            background["seed"] = seed
        return result, "job"
    selected = secrets.choice(tuple(THEMES)) if theme == "random" else theme
    if theme == "random" and seed is None:
        seed = secrets.randbelow(2**32)
    # Keep motion controls for existing cosmic jobs; static jobs get an animated default.
    background = background if background["kind"] == "cosmic" else {"kind": "cosmic"}
    background.update(THEMES["aurora" if selected == PRESET else selected])
    if seed is not None:
        background["seed"] = seed
    result["background"] = normalize_cosmic_background(background)
    if selected == PRESET:
        apply_lyrics_plus(result)
    return result, selected

import re
from dataclasses import asdict, dataclass
from typing import Any

HEX_COLOR_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")
ASS_COLOR_PATTERN = re.compile(r"^&H([0-9a-fA-F]{2})?([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$")


def normalize_hex_color(value: str, default: str = "#FFFFFF") -> str:
    """Normalize a hex color string to uppercase #RRGGBB."""
    if not isinstance(value, str):
        return default
    match = HEX_COLOR_PATTERN.match(value.strip())
    if not match:
        return default
    return f"#{match.group(1).upper()}"


def hex_to_ass_color(hex_str: str, alpha: float = 1.0) -> str:
    """Convert a hex color (#RRGGBB) and alpha opacity (0.0-1.0) to ASS format &HAABBGGRR."""
    normalized = normalize_hex_color(hex_str, default="#FFFFFF").lstrip("#")
    r = int(normalized[0:2], 16)
    g = int(normalized[2:4], 16)
    b = int(normalized[4:6], 16)
    clamped_alpha = max(0.0, min(1.0, float(alpha)))
    # ASS alpha: 0x00 is fully opaque, 0xFF is fully transparent
    ass_alpha = max(0, min(255, round((1.0 - clamped_alpha) * 255)))
    return f"&H{ass_alpha:02X}{b:02X}{g:02X}{r:02X}"


def ass_to_hex_color(ass_color: str) -> tuple[str, float]:
    """Convert an ASS color (&HAABBGGRR) to (#RRGGBB, alpha_opacity)."""
    if not isinstance(ass_color, str):
        return ("#FFFFFF", 1.0)
    match = ASS_COLOR_PATTERN.match(ass_color.strip())
    if not match:
        return ("#FFFFFF", 1.0)
    raw_alpha, raw_b, raw_g, raw_r = match.groups()
    r = int(raw_r, 16)
    g = int(raw_g, 16)
    b = int(raw_b, 16)
    ass_alpha = int(raw_alpha, 16) if raw_alpha is not None else 0
    alpha = 1.0 - (ass_alpha / 255.0)
    return (f"#{r:02X}{g:02X}{b:02X}", max(0.0, min(1.0, round(alpha, 2))))


@dataclass(frozen=True)
class StyleConfig:
    """Typography and visual styling for ASS subtitles and video canvas."""

    font_family: str = "DejaVu Sans"
    font_size: int = 64
    bold: bool = True
    italic: bool = False
    primary_color: str = "#FFD700"
    highlight_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 4
    shadow_color: str = "#000000"
    shadow_depth: int = 1
    shadow_opacity: float = 0.44
    alignment: int = 5
    margin_v: int = 70
    margin_h: int = 70
    overlay_opacity: float = 0.38
    line_gap_factor: float = 1.35

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, height: int = 1080) -> "StyleConfig":
        """Create a StyleConfig with sensible defaults scaled to video resolution."""
        is_hd = height >= 1080
        default_font_size = 64 if is_hd else 46
        default_margin = 70 if is_hd else 48

        if not data or not isinstance(data, dict):
            return cls(
                font_size=default_font_size,
                margin_v=default_margin,
                margin_h=default_margin,
            )

        font_family = str(data.get("font_family") or "DejaVu Sans").strip() or "DejaVu Sans"
        font_size = int(data.get("font_size") or default_font_size)
        bold = bool(data.get("bold", True))
        italic = bool(data.get("italic", False))
        primary_color = normalize_hex_color(str(data.get("primary_color", "#FFD700")), default="#FFD700")
        highlight_color = normalize_hex_color(str(data.get("highlight_color", "#FFFFFF")), default="#FFFFFF")
        outline_color = normalize_hex_color(str(data.get("outline_color", "#000000")), default="#000000")
        outline_width = max(0, int(data.get("outline_width", 4)))
        shadow_color = normalize_hex_color(str(data.get("shadow_color", "#000000")), default="#000000")
        shadow_depth = max(0, int(data.get("shadow_depth", 1)))
        shadow_opacity = max(0.0, min(1.0, float(data.get("shadow_opacity", 0.44))))
        alignment = int(data.get("alignment", 5))
        if alignment not in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
            alignment = 5
        margin_v = max(0, int(data.get("margin_v", default_margin)))
        margin_h = max(0, int(data.get("margin_h", default_margin)))
        overlay_opacity = max(0.0, min(1.0, float(data.get("overlay_opacity", 0.38))))
        line_gap_factor = max(1.0, min(2.5, float(data.get("line_gap_factor", 1.35))))

        return cls(
            font_family=font_family,
            font_size=font_size,
            bold=bold,
            italic=italic,
            primary_color=primary_color,
            highlight_color=highlight_color,
            outline_color=outline_color,
            outline_width=outline_width,
            shadow_color=shadow_color,
            shadow_depth=shadow_depth,
            shadow_opacity=shadow_opacity,
            alignment=alignment,
            margin_v=margin_v,
            margin_h=margin_h,
            overlay_opacity=overlay_opacity,
            line_gap_factor=line_gap_factor,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert style config to a JSON-serializable dictionary."""
        return asdict(self)

    def to_ass_style(self, name: str = "Default") -> str:
        """Generate a valid ASS v4+ Style definition line."""
        primary_ass = hex_to_ass_color(self.primary_color, alpha=1.0)
        secondary_ass = hex_to_ass_color(self.highlight_color, alpha=1.0)
        outline_ass = hex_to_ass_color(self.outline_color, alpha=1.0)
        shadow_ass = hex_to_ass_color(self.shadow_color, alpha=self.shadow_opacity)
        bold_val = -1 if self.bold else 0
        italic_val = -1 if self.italic else 0

        return (
            f"Style: {name},{self.font_family},{self.font_size},{primary_ass},{secondary_ass},{outline_ass},"
            f"{shadow_ass},{bold_val},{italic_val},0,0,100,100,0,0,1,{self.outline_width},{self.shadow_depth},"
            f"{self.alignment},{self.margin_h},{self.margin_h},{self.margin_v},1"
        )

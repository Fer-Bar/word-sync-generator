import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

HEX_COLOR_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")
ASS_COLOR_PATTERN = re.compile(r"^&H([0-9a-fA-F]{2})?([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$")

DEFAULT_AGENT_PALETTE: tuple[tuple[str, str], ...] = (
    ("#FFD700", "#FFFFFF"),  # Gold / White (Agent 1)
    ("#00D7FF", "#FFFFFF"),  # Cyan / White (Agent 2)
    ("#FF5376", "#FFFFFF"),  # Pink / White (Agent 3)
    ("#22C55E", "#FFFFFF"),  # Green / White (Agent 4)
    ("#F97316", "#FFFFFF"),  # Orange / White (Agent 5)
    ("#A855F7", "#FFFFFF"),  # Purple / White (Agent 6)
)

RECOMMENDED_PALETTES: list[dict[str, str]] = [
    {"name": "Gold & White", "primary": "#FFD700", "highlight": "#FFFFFF"},
    {"name": "Cyber Cyan", "primary": "#64748B", "highlight": "#00E5FF"},
    {"name": "Pop Magenta", "primary": "#F1F5F9", "highlight": "#FF2E93"},
    {"name": "Emerald Glow", "primary": "#CBD5E1", "highlight": "#10B981"},
    {"name": "Sunset Coral", "primary": "#FDE047", "highlight": "#FF5722"},
    {"name": "Ultra Violet", "primary": "#E0E7FF", "highlight": "#A855F7"},
    {"name": "Electric Yellow", "primary": "#94A3B8", "highlight": "#FFE600"},
    {"name": "High Contrast", "primary": "#6B7280", "highlight": "#FFFFFF"},
]


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


DEFAULT_LYRICS_COLORS: dict[str, str] = {
    "inactive": "#9A8F8B",
    "active": "#F4EEE6",
}


def validate_config_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    """Reject malformed configuration objects and unknown keys."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = value.keys() - keys
    if unknown:
        raise ValueError(f"{label} has unknown keys: {', '.join(sorted(map(str, unknown)))}")
    return value


def validate_number(value: Any, label: str, minimum: float, maximum: float = math.inf) -> float:
    """Validate a finite JSON number without coercing strings or booleans."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not minimum <= value <= maximum
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        raise ValueError(f"{label} must be a finite number between {minimum} and {maximum}")
    return value


def validate_color(value: Any, label: str) -> str:
    """Validate and normalize a configured RGB color."""
    color = normalize_hex_color(value, default="")
    if not color:
        raise ValueError(f"{label} must use #RRGGBB")
    return color


@dataclass(frozen=True)
class StyleConfig:
    """Typography and visual styling for ASS subtitles and video canvas."""

    lyrics_effect: str = "classic"
    font_family: str = "DejaVu Sans"
    font_size: int = 64
    bold: bool = True
    italic: bool = False
    primary_color: str = "#FFD700"
    highlight_color: str = "#FFFFFF"
    coros_color: str = "#94A3B8"
    outline_color: str = "#000000"
    outline_width: int = 4
    shadow_color: str = "#000000"
    shadow_depth: int = 1
    shadow_opacity: float = 0.44
    alignment: int = 5
    margin_v: int = 70
    margin_h: int = 70
    line_gap_factor: float = 1.35
    agent_colors: dict[str, dict[str, str]] = field(default_factory=dict)
    lyrics_colors: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, height: int = 1080) -> "StyleConfig":
        """Create a StyleConfig with sensible defaults scaled to video resolution."""
        is_hd = height >= 1080
        default_font_size = 64 if is_hd else 46
        default_margin = 70 if is_hd else 48

        if data is not None:
            validate_config_object(
                data, set(cls.__dataclass_fields__), "style"
            )
            if data.get("lyrics_effect", "classic") not in ("classic", "word-synced"):
                raise ValueError("style.lyrics_effect must be classic or word-synced")
            for key in ("bold", "italic"):
                if key in data and not isinstance(data[key], bool):
                    raise ValueError(f"style.{key} must be a boolean")
            if "font_family" in data and (
                not isinstance(data["font_family"], str) or not data["font_family"].strip()
            ):
                raise ValueError("style.font_family must be a nonempty string")
            for key in ("font_size", "outline_width", "shadow_depth", "alignment", "margin_v", "margin_h"):
                if key in data:
                    minimum = 1 if key in {"font_size", "alignment"} else 0
                    validate_number(data[key], f"style.{key}", minimum, 9 if key == "alignment" else math.inf)
                    if not isinstance(data[key], int):
                        raise ValueError(f"style.{key} must be an integer")
            for key, bounds in {
                "shadow_opacity": (0, 1), "line_gap_factor": (1, 2.5)
            }.items():
                if key in data:
                    validate_number(data[key], f"style.{key}", *bounds)
            for key in (
                "primary_color", "highlight_color", "coros_color", "outline_color", "shadow_color"
            ):
                if key in data:
                    validate_color(data[key], f"style.{key}")
            if "agent_colors" in data:
                agents = data["agent_colors"]
                if not isinstance(agents, dict):
                    raise ValueError("style.agent_colors must be an object")
                for name, colors in agents.items():
                    if not isinstance(name, str) or not name.strip():
                        raise ValueError("style.agent_colors names must be nonempty strings")
                    validate_config_object(colors, {"primary_color", "highlight_color", "coros_color"}, "agent_colors")
                    for key, color in colors.items():
                        validate_color(color, f"style.agent_colors.{name}.{key}")
            if "lyrics_colors" in data:
                colors = validate_config_object(data["lyrics_colors"], {"inactive", "active"}, "style.lyrics_colors")
                for key, color in colors.items():
                    validate_color(color, f"style.lyrics_colors.{key}")

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
        coros_color = normalize_hex_color(
            str(data.get("coros_color") or "#94A3B8"),
            default="#94A3B8",
        )
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
        line_gap_factor = max(1.0, min(2.5, float(data.get("line_gap_factor", 1.35))))

        raw_agent_colors = data.get("agent_colors")
        normalized_agent_colors: dict[str, dict[str, str]] = {}
        if isinstance(raw_agent_colors, dict):
            for agent_name, colors in raw_agent_colors.items():
                if not isinstance(agent_name, str) or not agent_name.strip():
                    continue
                if isinstance(colors, dict):
                    p = normalize_hex_color(str(colors.get("primary_color", "")), default="")
                    h = normalize_hex_color(str(colors.get("highlight_color", "")), default="")
                    c = normalize_hex_color(str(colors.get("coros_color", "")), default="")
                    entry: dict[str, str] = {
                        "primary_color": p or primary_color,
                        "highlight_color": h or highlight_color,
                    }
                    if c:
                        entry["coros_color"] = c
                    normalized_agent_colors[agent_name.strip()] = entry

        raw_lyrics_colors = data.get("lyrics_colors")
        normalized_lyrics_colors: dict[str, str] | None = None
        if isinstance(raw_lyrics_colors, dict):
            normalized_lyrics_colors = {
                "inactive": normalize_hex_color(
                    str(raw_lyrics_colors.get("inactive") or DEFAULT_LYRICS_COLORS["inactive"]),
                    default=DEFAULT_LYRICS_COLORS["inactive"],
                ),
                "active": normalize_hex_color(
                    str(raw_lyrics_colors.get("active") or DEFAULT_LYRICS_COLORS["active"]),
                    default=DEFAULT_LYRICS_COLORS["active"],
                ),
            }

        return cls(
            lyrics_effect=data.get("lyrics_effect", "classic"),
            font_family=font_family,
            font_size=font_size,
            bold=bold,
            italic=italic,
            primary_color=primary_color,
            highlight_color=highlight_color,
            coros_color=coros_color,
            outline_color=outline_color,
            outline_width=outline_width,
            shadow_color=shadow_color,
            shadow_depth=shadow_depth,
            shadow_opacity=shadow_opacity,
            alignment=alignment,
            margin_v=margin_v,
            margin_h=margin_h,
            line_gap_factor=line_gap_factor,
            agent_colors=normalized_agent_colors,
            lyrics_colors=normalized_lyrics_colors,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert style config to a JSON-serializable dictionary."""
        result = asdict(self)
        if self.lyrics_colors is None:
            result.pop("lyrics_colors", None)
        return result

    def get_lyrics_colors(self) -> dict[str, str]:
        """Return resolved lyrics colors dictionary."""
        return dict(self.lyrics_colors) if self.lyrics_colors else dict(DEFAULT_LYRICS_COLORS)

    def get_agent_colors(
        self,
        agent: str | None = None,
        index: int = 0,
        is_background: bool = False,
    ) -> tuple[str, str]:
        """Return (primary_color, highlight_color) for an agent or vocal channel."""
        if is_background and (not agent or agent not in self.agent_colors):
            return (self.coros_color, self.highlight_color)
        if agent and agent in self.agent_colors:
            cfg = self.agent_colors[agent]
            if is_background:
                p = cfg.get("coros_color") or self.coros_color
            else:
                p = cfg.get("primary_color") or self.primary_color
            h = cfg.get("highlight_color") or self.highlight_color
            return (p, h)
        if agent:
            palette_idx = index % len(DEFAULT_AGENT_PALETTE)
            fallback_primary, fallback_highlight = DEFAULT_AGENT_PALETTE[palette_idx]
            return (fallback_primary, fallback_highlight)
        return (self.primary_color, self.highlight_color)

    def to_ass_style(
        self,
        name: str = "Default",
        *,
        primary_color: str | None = None,
        highlight_color: str | None = None,
        outline_color: str | None = None,
        italic: bool | None = None,
        font_size: int | None = None,
    ) -> str:
        """Generate a valid ASS v4+ Style definition line."""
        p_col = normalize_hex_color(primary_color, default=self.primary_color) if primary_color else self.primary_color
        h_col = (
            normalize_hex_color(highlight_color, default=self.highlight_color)
            if highlight_color
            else self.highlight_color
        )
        out_col = (
            normalize_hex_color(outline_color, default=self.outline_color) if outline_color else self.outline_color
        )
        primary_ass = hex_to_ass_color(p_col, alpha=1.0)
        secondary_ass = hex_to_ass_color(h_col, alpha=1.0)
        outline_ass = hex_to_ass_color(out_col, alpha=1.0)
        shadow_ass = hex_to_ass_color(self.shadow_color, alpha=self.shadow_opacity)
        bold_val = -1 if self.bold else 0
        is_italic = self.italic if italic is None else italic
        italic_val = -1 if is_italic else 0
        f_size = font_size if font_size is not None else self.font_size

        return (
            f"Style: {name},{self.font_family},{f_size},{primary_ass},{secondary_ass},{outline_ass},"
            f"{shadow_ass},{bold_val},{italic_val},0,0,100,100,0,0,1,{self.outline_width},{self.shadow_depth},"
            f"{self.alignment},{self.margin_h},{self.margin_h},{self.margin_v},1"
        )

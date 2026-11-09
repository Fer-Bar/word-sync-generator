import copy
import json
from pathlib import Path
from typing import Any

from karaoke_app.resources import PROJECT_ROOT, logo_resource
from karaoke_app.style import StyleConfig, validate_color, validate_config_object, validate_number

JOB_FILENAME = "job.json"
DEFAULT_BANNER_RELATIVE = "logos/banner.png"


def load_job_document(job_dir: Path) -> dict[str, Any]:
    """Load a normalized v2 job, migrating v1 in memory without rewriting it."""
    path = job_dir.expanduser().resolve() / JOB_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"Missing prepared job document: {path}")
    try:
        return validate_job_document(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid {JOB_FILENAME}: {error}") from error


def validate_job_document(value: Any) -> dict[str, Any]:
    """Validate durable rendering configuration and preserve extensible provenance."""
    validate_config_object(value, {
        "schema_version", "job_id", "title", "source", "alignment", "metadata", "preparation",
        "media", "video", "background", "style", "lyrics_colors", "watermark", "intro", "thumbnail",
    }, "job.json")
    version = value.get("schema_version")
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("job.json schema_version must be 1 or 2")
    title = value.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("job.json title is required")
    job_id = value.get("job_id", "")
    if not isinstance(job_id, str):
        raise ValueError("job.json job_id must be a string")
    result = {"schema_version": 2, "job_id": job_id, "title": title.strip()}
    for key in ("source", "alignment", "metadata", "preparation"):
        if key in value or key in {"source", "alignment"}:
            item = value.get(key, {})
            if not isinstance(item, dict):
                raise ValueError(f"{key} must be an object")
            result[key] = copy.deepcopy(item)

    media_keys = {"original_audio", "vocals_audio", "instrumental_audio", "lyrics"}
    media = validate_config_object(value.get("media"), media_keys, "media")
    result["media"] = {key: _relative_path(media.get(key), f"media.{key}") for key in sorted(media_keys)}
    video = validate_config_object(value.get("video"), {"width", "height", "fps"}, "video")
    for key in ("width", "height", "fps"):
        if type(video.get(key)) is not int or video[key] <= 0:
            raise ValueError(f"video.{key} must be a positive integer")
    for key in ("width", "height"):
        if video[key] % 2:
            raise ValueError(f"video.{key} must be even for H.264 video")
    if video["fps"] > 120:
        raise ValueError("video.fps must not exceed 120")
    result["video"] = dict(video)

    background = value.get("background")
    if isinstance(background, dict) and background.get("kind") == "cosmic":
        from karaoke_app.cosmic_background import normalize_cosmic_background

        background = normalize_cosmic_background(background)
    else:
        background = validate_config_object(
            background, {"kind", "color", "path", "overlay_opacity", "crop_right"}, "background"
        )
    kind = background.get("kind")
    if kind not in ("solid", "image", "video", "cosmic"):
        raise ValueError("background.kind must be solid, image, video or cosmic")
    if kind == "cosmic":
        normalized_background = background
    elif kind == "solid":
        validate_config_object(background, {"kind", "color", "overlay_opacity"}, "background")
        if "overlay_opacity" in background:
            validate_number(background["overlay_opacity"], "background.overlay_opacity", 0, 1)
        normalized_background = {"kind": kind, "color": validate_color(background.get("color"), "background.color")}
    else:
        if "color" in background:
            validate_color(background["color"], "background.color")
        # v1 renderers ignored style.overlay_opacity; preserve actual rendered opacity.
        opacity = background.get("overlay_opacity", 0.38 if version == 1 else 0)
        normalized_background = {
            "kind": kind,
            "path": _relative_path(background.get("path"), "background.path"),
            "overlay_opacity": validate_number(opacity, "background.overlay_opacity", 0, 1),
        }
    if kind in {"image", "video"} and "crop_right" in background:
        normalized_background["crop_right"] = validate_number(
            background["crop_right"], "background.crop_right", 0, 0.5
        )
    result["background"] = normalized_background

    style = value.get("style", {})
    if not isinstance(style, dict):
        raise ValueError("style must be an object")
    style = dict(style)
    if version == 1:
        style.pop("overlay_opacity", None)
    elif "overlay_opacity" in style:
        raise ValueError("style.overlay_opacity belongs in background.overlay_opacity")
    if "lyrics_colors" in value:
        colors = validate_config_object(value["lyrics_colors"], {"inactive", "active"}, "lyrics_colors")
        for key, color in colors.items():
            validate_color(color, f"lyrics_colors.{key}")
        style.setdefault("lyrics_colors", colors)
    result["style"] = StyleConfig.from_dict(style, height=video["height"]).to_dict()

    watermark = value.get("watermark", {"enabled": version == 1 and (PROJECT_ROOT / DEFAULT_BANNER_RELATIVE).is_file()})
    validate_config_object(watermark, {"enabled", "path", "position", "scale", "margin", "opacity"}, "watermark")
    enabled = watermark.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("watermark.enabled must be a boolean")
    normalized_watermark = {"enabled": enabled}
    if "path" in watermark or enabled:
        path = watermark.get("path", DEFAULT_BANNER_RELATIVE if version == 1 else None)
        if not isinstance(path, str) or not path.strip() or ".." in Path(path).parts or "\x00" in path:
            raise ValueError("watermark.path must be a path string without traversal")
        normalized_watermark["path"] = path.strip()
    position = watermark.get("position", "top_left")
    if position not in ("top_left", "top_right", "bottom_left", "bottom_right"):
        raise ValueError("watermark.position must be top_left, top_right, bottom_left, or bottom_right")
    if enabled or "position" in watermark:
        normalized_watermark["position"] = position
    for key, default, lower, upper in (("scale", 0.18, 0.01, 0.5), ("margin", 0.05, 0, 0.2), ("opacity", 0.85, 0, 1)):
        if enabled or key in watermark:
            normalized_watermark[key] = validate_number(watermark.get(key, default), f"watermark.{key}", lower, upper)
    result["watermark"] = normalized_watermark

    if "intro" in value:
        intro = validate_config_object(
            value["intro"], {"enabled", "title", "artist", "logo", "start", "duration", "end", "align",
                             "graphic_style", "title_layout", "graphic_palette"}, "intro"
        )
        normalized_intro = {"enabled": intro.get("enabled", True)}
        if not isinstance(normalized_intro["enabled"], bool):
            raise ValueError("intro.enabled must be a boolean")
        for key in ("title", "artist"):
            if key in intro:
                if not isinstance(intro[key], str):
                    raise ValueError(f"intro.{key} must be a string")
                normalized_intro[key] = intro[key].strip()
        if "align" in intro:
            if intro["align"] not in ("start", "center", "end"):
                raise ValueError("intro.align must be start, center or end")
            normalized_intro["align"] = intro["align"]
        for key, choices in (("graphic_style", ("default", "fomo", "fomo-xerox")),
                             ("title_layout", ("stacked", "wide")), ("graphic_palette", ("light", "dark"))):
            if key in intro:
                if intro[key] not in choices:
                    raise ValueError(f"intro.{key} must be one of {choices}")
                normalized_intro[key] = intro[key]
        if "logo" in intro:
            normalized_intro["logo"] = _relative_path(intro["logo"], "intro.logo")
        for key in ("start", "duration", "end"):
            if key in intro:
                normalized_intro[key] = validate_number(intro[key], f"intro.{key}", 0)
        if "duration" in intro and intro["duration"] <= 0:
            raise ValueError("intro.duration must be a positive number")
        if "end" in intro and intro["end"] <= intro.get("start", 0):
            raise ValueError("intro.end must be greater than intro.start")
        result["intro"] = normalized_intro
    if "thumbnail" in value:
        thumbnail = validate_config_object(value["thumbnail"], {"time", "align"}, "thumbnail")
        normalized_thumbnail = {}
        if "time" in thumbnail:
            normalized_thumbnail["time"] = validate_number(thumbnail["time"], "thumbnail.time", 0)
        if "align" in thumbnail:
            if thumbnail["align"] not in ("start", "center", "end"):
                raise ValueError("thumbnail.align must be start, center or end")
            normalized_thumbnail["align"] = thumbnail["align"]
        result["thumbnail"] = normalized_thumbnail
    return result


def resolve_job_asset(job_dir: Path, relative_path: str, label: str) -> Path:
    """Resolve a required job asset without allowing path traversal."""
    root = job_dir.expanduser().resolve()
    resolved = (root / _relative_path(relative_path, label)).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise FileNotFoundError(f"Missing {label}: {resolved}")
    return resolved


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be a relative job path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a relative job path")
    return path.as_posix()


def resolve_watermark_path(job_dir: Path, path_str: str | None = None) -> Path:
    """Resolve explicit local/project/external images without substituting a default."""
    requested = DEFAULT_BANNER_RELATIVE if path_str is None else path_str
    if not isinstance(requested, str) or not requested.strip() or "\x00" in requested:
        raise ValueError("watermark.path must be a path string")
    candidate = Path(requested).expanduser()
    if ".." in candidate.parts:
        raise ValueError(f"Path traversal not permitted: {requested}")
    if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise ValueError(f"Unsupported watermark image: {requested}")
    if candidate.is_absolute():
        if candidate.is_file():
            return candidate.resolve()
    else:
        for root in (job_dir.expanduser().resolve(), PROJECT_ROOT.resolve()):
            resolved = (root / candidate).resolve()
            if resolved.is_relative_to(root) and resolved.is_file():
                return resolved
    if requested == DEFAULT_BANNER_RELATIVE and logo_resource("banner.png").is_file():
        return logo_resource("banner.png")
    raise FileNotFoundError(f"Missing watermark asset: {requested}")

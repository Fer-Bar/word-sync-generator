import json
import re
from pathlib import Path
from typing import Any

JOB_FILENAME = "job.json"


def load_job_document(job_dir: Path) -> dict[str, Any]:
    """Load and validate a prepared karaoke job."""
    path = job_dir.expanduser().resolve() / JOB_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"Missing prepared job document: {path}")
    try:
        return validate_job_document(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid {JOB_FILENAME}: {error}") from error


def validate_job_document(value: Any) -> dict[str, Any]:
    """Validate media and rendering configuration for a prepared job."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("job.json schema_version must be 1")
    media = value.get("media")
    video = value.get("video")
    background = value.get("background")
    if not isinstance(media, dict) or not isinstance(video, dict) or not isinstance(background, dict):
        raise ValueError("job.json media, video, and background must be objects")

    normalized_media = {
        key: _relative_path(media.get(key), f"media.{key}")
        for key in ("original_audio", "vocals_audio", "instrumental_audio", "lyrics")
    }
    normalized_video = {}
    for key in ("width", "height", "fps"):
        item = video.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise ValueError(f"video.{key} must be a positive integer")
        normalized_video[key] = item

    kind = background.get("kind")
    if kind not in {"solid", "image"}:
        raise ValueError("background.kind must be solid or image")
    color = background.get("color")
    if not isinstance(color, str) or not re.fullmatch(r"#?[0-9a-fA-F]{6}", color):
        raise ValueError("background.color must use #RRGGBB")
    normalized_background: dict[str, Any] = {"kind": kind, "color": f"#{color.lstrip('#').upper()}"}
    if kind == "image":
        normalized_background["path"] = _relative_path(background.get("path"), "background.path")
    if "overlay_opacity" in background:
        try:
            normalized_background["overlay_opacity"] = max(0.0, min(1.0, float(background["overlay_opacity"])))
        except (ValueError, TypeError):
            pass

    title = value.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("job.json title is required")
    from karaoke_app.style import StyleConfig

    style_data = value.get("style")
    normalized_style = (
        StyleConfig.from_dict(style_data, height=normalized_video["height"]).to_dict()
        if isinstance(style_data, dict)
        else None
    )
    result = {
        "schema_version": 1,
        "job_id": str(value.get("job_id") or ""),
        "title": title.strip(),
        "source": value.get("source") if isinstance(value.get("source"), dict) else {},
        "alignment": value.get("alignment") if isinstance(value.get("alignment"), dict) else {},
        "media": normalized_media,
        "video": normalized_video,
        "background": normalized_background,
    }
    if normalized_style is not None:
        result["style"] = normalized_style
    return result


def resolve_job_asset(job_dir: Path, relative_path: str, label: str) -> Path:
    """Resolve a required job asset without allowing path traversal."""
    root = job_dir.expanduser().resolve()
    resolved = (root / _relative_path(relative_path, label)).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise FileNotFoundError(f"Missing {label}: {resolved}")
    return resolved


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a relative job path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a relative job path")
    return path.as_posix()

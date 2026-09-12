"""Shared CLI visual preferences saved at preparation and resolved at rendering."""

import copy
from pathlib import Path
from typing import Any

from karaoke_app.cosmic_background import normalize_cosmic_background
from karaoke_app.lyrics_plus import apply_lyrics_plus, apply_plus_typography, cover_palette
from karaoke_app.style import StyleConfig

VISUAL_STYLES = ("plus", "classic")
BACKGROUND_STYLES = ("fluid", "cosmic-sand")


def apply_visual_options(
    document: dict[str, Any], *, visual_style: str | None = None,
    background_style: str | None = None, cover: Path | None = None,
) -> dict[str, Any]:
    """Return a configured copy; omitted options preserve the job's saved appearance."""
    result = copy.deepcopy(document)
    if visual_style is not None and visual_style not in VISUAL_STYLES:
        raise ValueError(f"Unknown visual style: {visual_style}")
    if background_style is not None and background_style not in BACKGROUND_STYLES:
        raise ValueError(f"Unknown background style: {background_style}")
    if background_style:
        old = result["background"]
        background = old if old["kind"] == "cosmic" else {"kind": "cosmic"}
        result["background"] = normalize_cosmic_background(background)
        if background_style == "fluid":
            old_style = result.get("style")
            apply_lyrics_plus(result)
            if old_style is None:
                result.pop("style", None)
            else:
                result["style"] = old_style
        else:
            result["background"].update({"appearance": "cosmic", "detail": 0.65,
                "overlay_opacity": 0, "brightness": 1, "contrast": 1.4})
    if cover:
        if result["background"]["kind"] != "cosmic":
            raise ValueError("--cover requires a fluid or cosmic-sand background")
        result["background"].update(cover_palette(cover.expanduser().resolve()))
    if visual_style == "plus":
        apply_plus_typography(result)
    elif visual_style == "classic":
        result["style"] = StyleConfig.from_dict(None, height=result["video"]["height"]).to_dict()
    return result


def preparation_visuals(video: dict[str, int], args: Any) -> dict[str, Any]:
    """Resolve portable visual defaults before provisioning the remote preparation job."""
    static = bool(getattr(args, "background_image", None) or getattr(args, "background_color", None))
    background_style = getattr(args, "background_style", None)
    if static and background_style:
        raise ValueError("Choose --background-style or a static --background-image/--background-color")
    if static and getattr(args, "cover", None):
        raise ValueError("--cover requires a procedural background")
    document = apply_visual_options(
        {"video": video, "background": {"kind": "solid", "color": "#0B1020"}},
        visual_style=getattr(args, "visual_style", "plus"),
        background_style=background_style or (None if static else "fluid"),
        cover=getattr(args, "cover", None),
    )
    return {"render_style": document["style"],
            **({} if static else {"render_background": document["background"]})}


def configure_job(job_dir: Path, *, visual_style: str = "plus", background_style: str | None = None,
                  cover: Path | None = None) -> Path:
    """Save visual preferences atomically with a byte-for-byte backup of the previous job."""
    import hashlib
    import json
    import tempfile

    from karaoke_app.job_document import load_job_document, validate_job_document

    root = job_dir.expanduser().resolve()
    path = root / "job.json"
    original = path.read_bytes()
    document = validate_job_document(apply_visual_options(load_job_document(root), visual_style=visual_style,
                                      background_style=background_style, cover=cover))
    if document == json.loads(original):
        return path
    backup = root / "backups" / f"job-{hashlib.sha256(original).hexdigest()[:12]}.json"
    backup.parent.mkdir(exist_ok=True)
    if backup.exists() and backup.read_bytes() != original:
        raise ValueError(f"Backup collision: {backup}")
    backup.write_bytes(original)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(document, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def run_configure(argv: list[str]) -> None:
    """Persist styles for an existing job without retranscription or a remote session."""
    import argparse
    import logging

    parser = argparse.ArgumentParser(prog="karaoke configure", description=__doc__)
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--visual-style", choices=VISUAL_STYLES, default="plus")
    parser.add_argument("--background-style", choices=BACKGROUND_STYLES)
    parser.add_argument("--cover", type=Path)
    args = parser.parse_args(argv)
    path = configure_job(args.job_dir, visual_style=args.visual_style,
                         background_style=args.background_style, cover=args.cover)
    logging.getLogger(__name__).info("Saved visual configuration: %s", path)

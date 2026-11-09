"""Shared CLI visual preferences saved at preparation and resolved at rendering."""

import copy
from pathlib import Path
from typing import Any

from karaoke_app.cosmic_background import normalize_cosmic_background
from karaoke_app.lyrics_plus import apply_lyrics_plus, apply_plus_typography, cover_palette
from karaoke_app.style import StyleConfig

VISUAL_STYLES = ("plus", "classic")
BACKGROUND_STYLES = ("fluid", "cosmic-sand")
PRESETS = {
    "fluid": {"visual_style": "plus", "background_style": "fluid", "graphic_style": "default"},
    "cosmic": {"visual_style": "plus", "background_style": "cosmic-sand", "graphic_style": "default"},
    "classic": {"visual_style": "classic", "background_color": "#0B1020", "graphic_style": "default"},
}


def preset_options(options: dict[str, Any]) -> dict[str, Any]:
    """Apply a named preset before explicit options, without conflicting backgrounds."""
    preset = options.get("preset")
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"Unknown preset: {preset}")
    result = dict(PRESETS.get(preset, {}))
    backgrounds = ("background_image", "background_video", "background_color", "background_style")
    if any(options.get(key) is not None for key in backgrounds):
        for key in backgrounds:
            result.pop(key, None)
    result.update({key: value for key, value in options.items() if value is not None})
    return result


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
    options = preset_options(vars(args))
    static = bool(options.get("background_image") or options.get("background_color"))
    background_style = options.get("background_style")
    if static and background_style:
        raise ValueError("Choose --background-style or a static --background-image/--background-color")
    if static and options.get("cover"):
        raise ValueError("--cover requires a procedural background")
    document = apply_visual_options(
        {"video": video, "background": {"kind": "solid", "color": options.get("background_color") or "#0B1020"}},
        visual_style=options.get("visual_style", "plus"),
        background_style=background_style or (None if static else "fluid"),
        cover=options.get("cover"),
    )
    return {"render_style": document["style"],
            **({"render_background": document["background"]} if not options.get("background_image") else {})}




def resolve_options(
    job_dir: Path, options: dict[str, Any], *, document: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Resolve saved settings and explicit overrides without copying or writing assets."""
    from karaoke_app.job_document import (
        load_job_document,
        resolve_job_asset,
        resolve_watermark_path,
        validate_job_document,
    )
    from karaoke_app.style import validate_color
    from karaoke_app.themes import apply_render_theme

    root = job_dir.expanduser().resolve()
    options = preset_options(options)
    document = copy.deepcopy(document) if document is not None else load_job_document(root)
    if options.get("resolution"):
        width, height = (1920, 1080) if options["resolution"] == "1080p" else (1280, 720)
        scale = height / document["video"]["height"]
        document["video"].update(width=width, height=height)
        # Keep custom typography proportional when changing the output canvas.
        for key in ("font_size", "margin_v", "margin_h", "outline_width", "shadow_depth"):
            if key in document.get("style", {}):
                document["style"][key] = round(document["style"][key] * scale)
    if options.get("fps") is not None:
        document["video"]["fps"] = options["fps"]
    if options.get("mode"):
        document["render"] = {"mode": options["mode"]}
    for key in ("title", "artist"):
        if options.get(key) is not None:
            if not isinstance(options[key], str) or (key == "title" and not options[key].strip()):
                raise ValueError(f"{key} must contain text")
            document.setdefault("intro", {})[key] = options[key].strip()
            if key == "title":
                document["title"] = options[key].strip()
    document, theme = apply_render_theme(document, options.get("theme") or "job")
    static = [options.get("background_image"), options.get("background_video"), options.get("background_color")]
    if sum(bool(value) for value in [*static, options.get("background_style")]) > 1:
        raise ValueError("Choose one background: procedural, image, video or solid color")
    if any(static):
        if options.get("theme") not in (None, "job"):
            raise ValueError("Named themes require a procedural background; omit --theme for an image or solid color")
        if options.get("cover"):
            raise ValueError("--cover requires a procedural background")
        if options.get("background_image") or options.get("background_video"):
            kind = "video" if options.get("background_video") else "image"
            asset = Path(options[f"background_{kind}"]).expanduser().resolve()
            if not asset.is_relative_to(root):
                raise ValueError(f"Background {kind} must be inside the project folder. Copy it there first.")
            relative = asset.relative_to(root).as_posix()
            resolve_job_asset(root, relative, f"background {kind}")
            if kind == "image":
                from PIL import Image

                with Image.open(asset) as picture:
                    picture.verify()
            document["background"] = {"kind": kind, "path": relative, "overlay_opacity": 0}
        else:
            document["background"] = {"kind": "solid",
                                      "color": validate_color(options["background_color"], "background color")}
    document = apply_visual_options(document, **{key: options.get(key) for key in
                                                ("visual_style", "background_style", "cover")})
    if options.get("background_style") and options.get("theme") not in (None, "job"):
        document, _ = apply_render_theme(document, theme)
        document = apply_visual_options(document, visual_style=options.get("visual_style"), cover=options.get("cover"))
    if options.get("seed") is not None:
        document, _ = apply_render_theme(document, "job", options["seed"])
    for key in ("graphic_style", "align"):
        if options.get(key) is not None:
            document.setdefault("intro", {})[key] = options[key]
    for option, field, kinds in (
        ("background_overlay_opacity", "overlay_opacity", {"image", "video", "cosmic"}),
        ("background_crop_right", "crop_right", {"image", "video"}),
    ):
        if options.get(option) is not None:
            if document["background"]["kind"] not in kinds:
                label = option.replace("_", "-")
                raise ValueError(f"--{label} requires a compatible image, video or procedural background")
            document["background"][field] = options[option]
    if options.get("font_size") is not None:
        document.setdefault("style", {})["font_size"] = options["font_size"]
    for phase in ("active", "inactive"):
        color = options.get(f"lyrics_{phase}_color")
        if color is not None:
            style = document.setdefault("style", {})
            style["lyrics_colors"] = {**(style.get("lyrics_colors") or {}), phase: color}
            style["primary_color" if phase == "active" else "highlight_color"] = color
    if options.get("intro") is not None:
        document.setdefault("intro", {})["enabled"] = options["intro"]
    if options.get("intro_duration") is not None and options.get("intro_end") is not None:
        raise ValueError("Choose --intro-duration or --intro-end, not both")
    for field in ("start", "duration", "end"):
        if options.get(f"intro_{field}") is not None:
            document.setdefault("intro", {})[field] = options[f"intro_{field}"]
            if field in {"duration", "end"}:
                document["intro"].pop("end" if field == "duration" else "duration", None)
    if options.get("thumbnail_time") is not None:
        document.setdefault("thumbnail", {})["time"] = options["thumbnail_time"]
    if options.get("thumbnail_align") is not None:
        document.setdefault("thumbnail", {})["align"] = options["thumbnail_align"]
    if options.get("no_logo"):
        document["watermark"] = {"enabled": False}
    else:
        watermark = document.get("watermark", {"enabled": False})
        if options.get("logo"):
            path = Path(options["logo"]).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Logo not found: {path}")
            from PIL import Image

            with Image.open(path) as picture:
                picture.verify()
            watermark = {**watermark, "enabled": True, "path": str(path)}
        if watermark.get("enabled"):
            resolve_watermark_path(root, watermark.get("path"))
            for key in ("position", "scale", "opacity"):
                if options.get(f"logo_{key}") is not None:
                    watermark[key] = options[f"logo_{key}"]
        if not watermark.get("enabled") and any(options.get(f"logo_{key}") is not None
                                                for key in ("position", "scale", "opacity")):
            raise ValueError("Choose --logo before adjusting a disabled watermark")
        document["watermark"] = watermark
    document = validate_job_document(document)
    if document["background"]["kind"] == "video":
        video = resolve_job_asset(root, document["background"]["path"], "background video")
        metadata = validate_background_video(video)
        duration = metadata.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            if document.get("thumbnail", {}).get("time", 0) >= duration:
                raise ValueError(f"Thumbnail time must be before the background video's end ({duration:g} seconds)")
    return document, theme


def validate_background_video(path: Path) -> dict[str, Any]:
    """Decode one frame so invalid or audio-only files fail before saving settings."""
    import imageio_ffmpeg

    frames = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgb24")
    try:
        metadata = next(frames)
        next(frames)
        return metadata
    except (OSError, RuntimeError, StopIteration) as error:
        raise ValueError(f"Background video has no decodable video frame: {path}") from error
    finally:
        frames.close()


def appearance_rows(document: dict) -> dict[str, str]:
    """Describe effective settings rather than implementation names."""
    background = document["background"]
    style, intro = document.get("style", {}), document.get("intro", {})
    watermark = document.get("watermark", {})
    video = document["video"]
    background_name = background.get("appearance", background["kind"])
    if background_name == "cosmic":
        background_name = "cosmic-sand"
    return {
        "Title": document["title"],
        "Artist": intro.get("artist") or document.get("source", {}).get("artist") or "—",
        "Output": document.get("render", {}).get("mode", "both"),
        "Intro": (f"Start {intro.get('start', 0)} s · " +
                  (f"end {intro['end']} s" if "end" in intro else f"duration {intro.get('duration', 'automatic')} s")
                  if intro.get("enabled", True) else "Disabled"),
        "Thumbnail time": str(document.get("thumbnail", {}).get("time", "automatic")),
        "Thumbnail alignment": document.get("thumbnail", {}).get("align", intro.get("align", "start")),
        "Background darkening": str(background.get("overlay_opacity", 0)),
        "Background right crop": str(background.get("crop_right", 0)),
        "Lyric colors": " / ".join(str(value) for value in (style.get("lyrics_colors") or {}).values()) or "Default",
        "Typography": f"{style.get('font_family', 'Default')} · {style.get('font_size', 'default')} px",
        "Background": str(background_name),
        "Background image / color": (str(background.get("path", background.get("color", "—")))
                                      if background["kind"] != "cosmic" else "—"),
        "Background palette": " / ".join(str(background[key]) for key in
                                            ("base_color", "color", "secondary_color") if key in background)
                              if background["kind"] == "cosmic" else "—",
        "Seed": str(background.get("seed", "—")),
        "Graphics": intro.get("graphic_style", "default"),
        "Alignment": intro.get("align", "start"),
        "Watermark": (f"{watermark.get('path')} · {watermark.get('position')} · "
                      f"scale {watermark.get('scale')} · opacity {watermark.get('opacity')}"
                      if watermark.get("enabled") else "Disabled"),
        "Video": f"{video['width']} × {video['height']} · {video['fps']} fps",
    }


def show_appearance(document, *, before=None, console=None):
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = console or Console(stderr=True)
    stacked = before is not None and console.width < 72
    table = Table(title="Appearance", show_header=before is not None)
    table.add_column("Setting", max_width=18 if console.width < 72 else None)
    if before is not None and not stacked:
        table.add_column("Saved")
    table.add_column("Changes" if stacked else "Selected")
    old = appearance_rows(before) if before else {}
    for key, value in appearance_rows(document).items():
        if value == "—" and (before is None or old[key] == "—"):
            continue
        if stacked:
            content = value if value == old[key] else f"Saved: {old[key]}\nSelected: {value}"
            table.add_row(Text(key), Text(content))
        else:
            table.add_row(Text(key), *([Text(old[key])] if before is not None else []), Text(str(value)))
    console.print(table)


def save_configuration(job_dir: Path, document: dict, *, expected: dict | None = None) -> Path:
    """Atomically save internal state, refusing to overwrite concurrent edits."""
    import json
    import tempfile

    from karaoke_app.job_document import STATE_FILENAME, validate_job_document

    path = job_dir.expanduser().resolve() / STATE_FILENAME
    document = validate_job_document(document)
    current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    if expected is not None and (current is None or validate_job_document(current) != expected):
        raise ValueError("Project changed while configuring. Reopen configure to avoid overwriting those changes.")
    if document == current:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(document, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def configure_job(job_dir: Path, **options) -> Path:
    """Persist explicit preferences; omitted preferences retain their saved values."""
    document, _ = resolve_options(job_dir, options)
    return save_configuration(job_dir, document)


def interactive_configuration(job_dir: Path, options: dict, *, console=None) -> Path | None:
    """Edit any section repeatedly; cancellation never modifies the project."""
    import sys

    from rich.console import Console
    from rich.prompt import Confirm, Prompt

    from karaoke_app.job_document import load_job_document
    from karaoke_app.project_editor import edit_section

    console = console or Console(stderr=True)
    if not console.is_terminal or not sys.stdin.isatty():
        raise ValueError("Interactive configuration requires a terminal. Use configure PROJECT with explicit flags.")
    saved = load_job_document(job_dir)
    document, _ = resolve_options(job_dir, options)
    show_appearance(document, console=console)
    sections = {"1": "Presets", "2": "Typography", "3": "Background", "4": "Title and artwork",
                "5": "Watermark", "6": "Video and output"}
    while True:
        console.print("\n" + " | ".join(f"{key}. {value}" for key, value in sections.items()), markup=False)
        console.print("7. Summary | 8. Save | 0. Cancel", markup=False)
        choice = Prompt.ask("Section", choices=[*sections, "7", "8", "0"], default="0", console=console)
        if choice == "0":
            console.print("Configuration unchanged.")
            return None
        if choice == "7":
            show_appearance(document, before=saved, console=console)
        elif choice == "8":
            show_appearance(document, before=saved, console=console)
            if Confirm.ask("Save configuration?", default=False, console=console):
                return save_configuration(job_dir, document, expected=saved)
        else:
            candidate = edit_section(job_dir, document, choice, console)
            if candidate is not None:
                document = candidate

def run_configure(argv: list[str]) -> None:
    """Persist styles without retranscription or a remote session."""
    import argparse
    import logging

    from karaoke_app.cli import build_render_parser

    parser = argparse.ArgumentParser(prog="karaoke configure",
                                     description="Configure project sections, presets and output settings.",
                                     parents=[build_render_parser()], add_help=False)
    for action in list(parser._actions):
        if action.dest in {"gpu", "auth", "timeout"}:
            parser._remove_action(action)
            for group in parser._action_groups:
                if action in group._group_actions:
                    group._group_actions.remove(action)
            for option in action.option_strings:
                parser._option_string_actions.pop(option, None)
    for group in parser._action_groups:
        if group.title == "Colab and output":
            group.title = "Diagnostics"
    parser.epilog = ("Examples: karaoke configure PROJECT; karaoke configure PROJECT --preset fluid; "
                     "karaoke render PROJECT.")
    parser.add_argument("--interactive", action="store_true", help="Choose appearance with optional prompts")
    args = parser.parse_args(argv)
    options = vars(args).copy()
    root = options.pop("job_dir").expanduser().resolve()
    interactive = options.pop("interactive")
    if args.dry_run:
        document, _ = resolve_options(root, options)
        show_appearance(document)
        return
    explicit = any(value.startswith("--") and value not in {"--interactive", "--verbose"} for value in argv)
    path = interactive_configuration(root, options) if interactive or not explicit else configure_job(root, **options)
    if path:
        logging.getLogger(__name__).info("Configuration saved. Render with: karaoke render %s", root)

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



def resolve_options(job_dir: Path, options: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Resolve saved settings and explicit overrides without copying or writing assets."""
    from karaoke_app.fomo import apply_graphic_options
    from karaoke_app.job_document import (
        load_job_document,
        resolve_job_asset,
        resolve_watermark_path,
        validate_job_document,
    )
    from karaoke_app.style import validate_color
    from karaoke_app.themes import apply_render_theme

    root = job_dir.expanduser().resolve()
    document, theme = apply_render_theme(load_job_document(root), options.get("theme") or "job")
    static = [options.get("background_image"), options.get("background_color")]
    if sum(bool(value) for value in [*static, options.get("background_style")]) > 1:
        raise ValueError("Choose one background: --background-style, --background-image or --background-color")
    if any(static):
        if options.get("theme") not in (None, "job"):
            raise ValueError("Named themes require a procedural background; omit --theme for an image or solid color")
        if options.get("cover"):
            raise ValueError("--cover requires a procedural background")
        if options.get("background_image"):
            image = Path(options["background_image"]).expanduser().resolve()
            if not image.is_relative_to(root):
                raise ValueError("Background image must be inside the job folder. Copy it there first.")
            relative = image.relative_to(root).as_posix()
            resolve_job_asset(root, relative, "background image")
            from PIL import Image

            with Image.open(image) as picture:
                picture.verify()
            document["background"] = {"kind": "image", "path": relative, "overlay_opacity": 0}
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
    document = apply_graphic_options(document, **{key: options.get(key) for key in
        ("graphic_style", "graphic_palette", "title_layout", "align")})
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
        document["watermark"] = watermark
    return validate_job_document(document), theme


def appearance_rows(document: dict) -> dict[str, str]:
    """Describe effective settings rather than implementation names."""
    background = document["background"]
    style, intro = document.get("style", {}), document.get("intro", {})
    watermark = document.get("watermark", {})
    video = document["video"]
    xerox = intro.get("graphic_style") == "fomo-xerox"
    background_name = background.get("appearance", background["kind"])
    if background_name == "cosmic":
        background_name = "cosmic-sand"
    return {
        "Typography": f"{style.get('font_family', 'Default')} · {style.get('font_size', 'default')} px",
        "Background": "Xerox poster" if xerox else str(background_name),
        "Background image / color": (str(background.get("path", background.get("color", "—")))
                                     if not xerox and background["kind"] != "cosmic" else "—"),
        "Background palette": " / ".join(str(background[key]) for key in
                                            ("base_color", "color", "secondary_color") if key in background)
                              if background["kind"] == "cosmic" and not xerox else "—",
        "Seed": str(background.get("seed", "—")) if not xerox else "—",
        "Graphics": intro.get("graphic_style", "default"),
        "Graphic palette": intro.get("graphic_palette", "light"),
        "Title layout": intro.get("title_layout", "stacked"),
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


def save_configuration(job_dir: Path, document: dict) -> Path:
    """Validate and atomically save only the job document."""
    import json
    import tempfile

    from karaoke_app.job_document import validate_job_document

    path = job_dir.expanduser().resolve() / "job.json"
    document = validate_job_document(document)
    if document == json.loads(path.read_text(encoding="utf-8")):
        return path
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
    """Edit a temporary selection; only the final save writes the job."""
    import sys
    import tempfile

    from rich.console import Console
    from rich.prompt import Confirm, Prompt

    from karaoke_app.job_document import load_job_document

    console = console or Console(stderr=True)
    if not console.is_terminal or not sys.stdin.isatty():
        raise ValueError("--interactive requires a terminal. Use configure JOB with explicit flags instead.")
    options = options.copy()
    if options.get("theme") == "random":
        import secrets

        from karaoke_app.themes import THEMES

        options["theme"] = secrets.choice(tuple(THEMES))
        if options.get("seed") is None:
            options["seed"] = secrets.randbelow(2**32)
    saved = load_job_document(job_dir)
    document, _ = resolve_options(job_dir, options)
    show_appearance(document, console=console)

    def choose(label, choices):
        console.print(label, markup=False)
        console.print("  0. Keep current", markup=False)
        for index, (value, description) in enumerate(choices, 1):
            console.print(f"  {index}. {value} — {description}", markup=False)
        selected = int(Prompt.ask("Choice", choices=[str(i) for i in range(len(choices) + 1)],
                                  default="0", console=console))
        return choices[selected - 1][0] if selected else None

    typography = choose("Typography", [("plus", "Animated word highlighting"), ("classic", "Classic subtitles")])
    if typography:
        options["visual_style"] = typography
    background = choose("Background", [("fluid", "Flowing color"), ("cosmic-sand", "Textured particles"),
                                       ("image", "Image inside the job folder"), ("solid", "Solid RGB color")])
    if background:
        for key in ("background_style", "background_image", "background_color", "cover"):
            options.pop(key, None)
        if background in {"image", "solid"}:
            options["theme"] = "job"
            options.pop("seed", None)
        if background == "image":
            value = Path(Prompt.ask("Image path (relative to job folder)", console=console)).expanduser()
            options["background_image"] = value if value.is_absolute() else job_dir / value
        elif background == "solid":
            options["background_color"] = Prompt.ask("Color (#RRGGBB)", console=console)
        else:
            options["background_style"] = background
    document, _ = resolve_options(job_dir, options)
    if document["background"]["kind"] == "cosmic":
        from karaoke_app.themes import THEMES

        theme = choose("Background palette", [(name, "Named color palette") for name in THEMES])
        if theme:
            options["theme"] = theme
        seed = Prompt.ask("Animation seed (Enter to keep current)", default="", console=console)
        if seed:
            options["seed"] = int(seed)
        artwork = Prompt.ask("Artwork palette path (Enter to keep current)", default="", console=console)
        if artwork:
            options["cover"] = Path(artwork)
    for key, label, choices in (
        ("graphic_style", "Graphics", [("default", "Standard"), ("fomo", "Poster"),
                                       ("fomo-xerox", "Xerox poster; replaces background")]),
        ("graphic_palette", "Graphic palette", [("light", "Light"), ("dark", "Dark")]),
        ("title_layout", "Title layout", [("stacked", "Multiple lines"), ("wide", "Wide title")]),
        ("align", "Alignment", [("start", "Left"), ("center", "Center"), ("end", "Right")]),
    ):
        value = choose(label, choices)
        if value:
            options[key] = value
    watermark = choose("Watermark", [("disabled", "Remove watermark"), ("image", "Choose a logo image")])
    if watermark == "disabled":
        options["no_logo"] = True
    elif watermark == "image":
        options["no_logo"] = False
        options["logo"] = Path(Prompt.ask("Logo path", console=console))
    document, _ = resolve_options(job_dir, options)
    if document["watermark"].get("enabled"):
        position = choose("Watermark position", [(key, key.replace("_", " ")) for key in
                                                ("top_left", "top_right", "bottom_left", "bottom_right")])
        if position:
            options["logo_position"] = position
        for key, label in (("logo_scale", "Scale (0.01–0.5)"), ("logo_opacity", "Opacity (0–1)")):
            value = Prompt.ask(f"{label} (Enter to keep current)", default="", console=console)
            if value:
                options[key] = float(value)
    document, _ = resolve_options(job_dir, options)
    show_appearance(document, before=saved, console=console)
    if (document["background"]["kind"] == "cosmic"
            and Confirm.ask("Preview background?", default=False, console=console)):
        from karaoke_app.cosmic_background import render_cosmic_video

        with tempfile.TemporaryDirectory(prefix="karaoke-preview-") as directory:
            preview = render_cosmic_video(document["background"], {"width": 640, "height": 360, "fps": 12},
                                          Path(directory) / "preview.mp4", duration=3)
            console.print(f"Preview: {preview}", markup=False)
            Prompt.ask("Open this file to review it, then press Enter", default="", console=console)
    if not Confirm.ask("Save appearance?", default=False, console=console):
        console.print("Configuration unchanged.")
        return None
    return save_configuration(job_dir, document)


def run_configure(argv: list[str]) -> None:
    """Persist styles without retranscription or a remote session."""
    import argparse
    import logging

    from karaoke_app.cli import build_render_parser

    parser = argparse.ArgumentParser(prog="karaoke configure", description="Save appearance for future renders.",
                                     parents=[build_render_parser()], add_help=False)
    for action in list(parser._actions):
        if action.dest in {"mode", "gpu", "auth", "timeout"}:
            parser._remove_action(action)
            for group in parser._action_groups:
                if action in group._group_actions:
                    group._group_actions.remove(action)
            for option in action.option_strings:
                parser._option_string_actions.pop(option, None)
    for group in parser._action_groups:
        if group.title == "Colab and output":
            group.title = "Diagnostics"
    parser.epilog = "Example: karaoke configure JOB --interactive. Render saved settings: karaoke render JOB."
    parser.add_argument("--interactive", action="store_true", help="Choose appearance with optional prompts")
    args = parser.parse_args(argv)
    options = vars(args).copy()
    root = options.pop("job_dir").expanduser().resolve()
    interactive = options.pop("interactive")
    if args.dry_run:
        document, _ = resolve_options(root, options)
        show_appearance(document)
        return
    path = interactive_configuration(root, options) if interactive else configure_job(root, **options)
    if path:
        logging.getLogger(__name__).info("Saved appearance: %s", path)

"""Section-based terminal editor. Each edit is validated before it is accepted."""

from pathlib import Path

from rich.prompt import Prompt

from karaoke_app.visual_config import PRESETS, resolve_options


def edit_section(root: Path, document: dict, section: str, console) -> dict | None:
    """Return a validated selection, preserving the previous state on any error."""
    def choose(label, choices):
        console.print(label, markup=False)
        console.print("  0. Keep current / Back", markup=False)
        for index, (value, description) in enumerate(choices, 1):
            console.print(f"  {index}. {description} ({value})", markup=False)
        choice = Prompt.ask("Choice", choices=[str(i) for i in range(len(choices) + 1)],
                            default="0", console=console)
        return choices[int(choice) - 1][0] if choice != "0" else None

    def ask(label):
        return Prompt.ask(f"{label} (Enter to keep current)", default="", console=console).strip()

    def number(label, cast, lower, upper):
        while True:
            text = ask(label)
            if not text:
                return None
            try:
                value = cast(text)
                if not lower <= value <= upper:
                    raise ValueError
                return value
            except ValueError:
                console.print(f"Enter a number from {lower} to {upper}.", style="red")

    def color(label):
        from karaoke_app.style import validate_color

        while True:
            value = ask(label)
            if not value:
                return None
            try:
                return validate_color(value, label)
            except ValueError as error:
                console.print(str(error), style="red", markup=False)

    def path(text):
        candidate = Path(text).expanduser()
        return candidate if candidate.is_absolute() else root / candidate

    selected = {}
    if section == "1":
        selected["preset"] = choose("Preset", [(name, description) for name, description in zip(
            PRESETS, ("Animated words and flowing color", "Animated words and particles", "Classic subtitles"),
            strict=True,
        )])
    elif section == "2":
        selected["visual_style"] = choose("Typography", [("plus", "Animated word highlighting"),
                                                          ("classic", "Classic subtitles")])
        if selected["visual_style"] is None:
            return None
        selected["font_size"] = number("Font size (pixels)", int, 1, 512)
        selected["lyrics_active_color"] = color("Active lyric color #RRGGBB")
        selected["lyrics_inactive_color"] = color("Inactive lyric color #RRGGBB")
    elif section == "3":
        background = choose("Background", [("fluid", "Flowing color"), ("cosmic-sand", "Particles"),
                                           ("image", "Image in project folder"), ("solid", "Solid color"),
                                           ("video", "Video in project folder")])
        if background is None:
            return None
        if background in {"image", "video"}:
            value = ask(f"{background.title()} path, relative to project")
            if not value:
                return None
            selected[f"background_{background}"] = path(value)
            selected["background_overlay_opacity"] = number("Dark overlay opacity", float, 0, 1)
            selected["background_crop_right"] = number("Right crop fraction", float, 0, 0.5)
        elif background == "solid":
            selected["background_color"] = color("Background color #RRGGBB")
            if selected["background_color"] is None:
                return None
        else:
            from karaoke_app.themes import THEMES

            selected["background_style"] = background
            selected["theme"] = choose("Palette", [(name, name.title()) for name in THEMES])
            selected["seed"] = number("Animation seed", int, 0, 2**32 - 1)
            value = ask("Artwork palette image path")
            if value:
                selected["cover"] = path(value)
            selected["background_overlay_opacity"] = number("Dark overlay opacity", float, 0, 1)
    elif section == "4":
        selected["title"] = ask("Title") or None
        selected["artist"] = ask("Artist") or None
        for key, label, choices in (
            ("align", "Alignment", [("start", "Left"), ("center", "Center"), ("end", "Right")]),
        ):
            selected[key] = choose(label, choices)
        enabled = choose("Title intro", [("enabled", "Enabled"), ("disabled", "Disabled")])
        if enabled:
            selected["intro"] = enabled == "enabled"
        if enabled == "enabled" or (enabled is None and document.get("intro", {}).get("enabled", True)):
            selected["intro_start"] = number("Intro start (seconds)", float, 0, 86400)
            timing = choose("Intro timing", [("duration", "Duration from start"), ("end", "Absolute end time")])
            if timing:
                selected[f"intro_{timing}"] = number(f"Intro {timing} (seconds)", float, 0.1, 86400)
        selected["thumbnail_time"] = number("Thumbnail background time (seconds)", float, 0, 86400)
        selected["thumbnail_align"] = choose("Thumbnail alignment", [("start", "Left"),
                                                                      ("center", "Center"), ("end", "Right")])
    elif section == "5":
        watermark = choose("Watermark", [("disabled", "Disable"), ("image", "Choose a logo"),
                                         ("adjust", "Adjust current logo")])
        if watermark is None:
            return None
        if watermark == "disabled":
            selected["no_logo"] = True
        else:
            if watermark == "image":
                value = ask("Logo image path")
                if not value:
                    return None
                selected["logo"] = path(value)
            elif not document.get("watermark", {}).get("enabled"):
                console.print("No logo enabled. Choose a logo first.", style="red")
                return None
            selected["logo_position"] = choose("Position", [(name, name.replace("_", " ")) for name in
                ("top_left", "top_right", "bottom_left", "bottom_right")])
            selected["logo_scale"] = number("Scale", float, 0.01, 0.5)
            selected["logo_opacity"] = number("Opacity", float, 0, 1)
    elif section == "6":
        selected["resolution"] = choose("Resolution", [("1080p", "Full HD"), ("720p", "HD")])
        selected["fps"] = number("Frames per second", int, 1, 120)
        selected["mode"] = choose("Output", [("both", "Karaoke and lyrics"),
                                               ("karaoke", "Instrumental"), ("lyrics", "Original audio")])
    else:
        raise ValueError(f"Unknown configuration section: {section}")
    try:
        result, _ = resolve_options(root, selected, document=document)
    except (OSError, ValueError) as error:
        console.print(f"Section unchanged: {error}", style="red", markup=False)
        return None
    console.print("Section updated. Save from the menu when ready.")
    return result

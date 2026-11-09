import argparse
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values

from karaoke_app.rendering import create_render_bundle as _create_render_bundle
from karaoke_app.resources import PACKAGE_ROOT, PROJECT_ROOT, logo_resource, runtime_resource
from karaoke_app.terminal import ProcessFailure, configure_logging, failure_summary, notify, run_process
from karaoke_app.themes import THEMES
from karaoke_app.upload_diagnostics import upload_failure_message, upload_size, warn_large_upload
from karaoke_app.visual_config import BACKGROUND_STYLES, PRESETS, VISUAL_STYLES, preparation_visuals

LOGGER = logging.getLogger("karaoke_app.cli")
COLAB_SCRIPT = runtime_resource("karaoke_job.py")
ASS_MODULE = PACKAGE_ROOT / "ass.py"
LYRICS_MODULE = PACKAGE_ROOT / "lyrics_file.py"
REFERENCES_MODULE = PACKAGE_ROOT / "lyric_references.py"
COLAB_REQUIREMENTS = runtime_resource("requirements.txt")
DEFAULT_COOKIES = PROJECT_ROOT / "cookies.txt"
DEFAULT_LOGO = logo_resource("banner.png")
REMOTE_JOB = Path("/content/karaoke_job.json")
REMOTE_ARCHIVE = Path("/content/karaoke_result.zip")
REMOTE_STATUS = Path("/content/karaoke_status.json")
REMOTE_HF_TOKEN = Path("/content/.hf_token")
REMOTE_LYRICS_MODULE = Path("/content/karaoke_lyrics_file.py")
REMOTE_REFERENCES_MODULE = Path("/content/karaoke_lyric_references.py")
REMOTE_LYRICS_TEXT = Path("/content/lyrics_reference.txt")
REMOTE_GENIUS_REFERENCE = Path("/content/genius_reference.json")
REMOTE_RENDER_JOB = Path("/content/karaoke_render_job.zip")
REMOTE_SOURCE_BUNDLE = Path("/content/karaoke_source_job.zip")
COLOR_PATTERN = re.compile(r"^#?[0-9a-fA-F]{6}$")


def organize_help(parser: argparse.ArgumentParser) -> None:
    """Group related settings while preserving existing command options."""
    parser.add_argument("--verbose", action="store_true", help="Show detailed process output for troubleshooting")
    groups = {
        "Appearance · typography, background and palette": {
            "visual_style", "background_style", "background_image", "background_color", "cover", "theme",
            "seed", "graphic_style", "align", "resolution", "mode", "preset",
            "fps", "title", "artist", "font_size", "lyrics_active_color", "lyrics_inactive_color",
            "intro", "intro_duration", "intro_start", "intro_end", "thumbnail_time", "thumbnail_align",
            "background_video", "background_overlay_opacity", "background_crop_right",
        },
        "Watermark": {"logo", "no_logo", "logo_position", "logo_scale", "logo_opacity"},
        "Colab and output": {"gpu", "auth", "timeout", "output_dir", "verbose"},
    }
    for title, names in groups.items():
        group = parser.add_argument_group(title)
        for action in list(parser._optionals._group_actions):
            if action.dest in names:
                parser._optionals._group_actions.remove(action)
                group._group_actions.append(action)
    parser.epilog = ("Commands: source, configure, status, validate, render, background, "
        "preview, thumbnail, intro, cleanup. "
        "Save appearance: karaoke configure JOB --visual-style plus --background-style fluid. "
        "Render saved settings: karaoke render JOB. Preview background: karaoke background JOB."
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the preparation command parser."""
    parser = argparse.ArgumentParser(description="Prepare karaoke audio and lyrics on Google Colab.",
        epilog="Commands: source, configure, status, validate, render, background, preview, thumbnail, intro, cleanup.")
    parser.add_argument("source", help="YouTube URL or local audio/video file")
    parser.add_argument("--language", default="en", help="Whisper language code")
    parser.add_argument("--title", help="Track title override used for LRCLIB matching")
    parser.add_argument("--artist", help="Artist override used for LRCLIB matching")
    parser.add_argument("--album", help="Album override used for LRCLIB matching")
    parser.add_argument("--lrclib-id", type=int, help="Use a specific LRCLIB record")
    parser.add_argument("--lyrics-text", type=Path, help="UTF-8 TXT reference with one lyric verse per line")
    parser.add_argument("--genius-url", help="Metadata-checked Genius song URL used when LRCLIB has no reference")
    parser.add_argument("--no-lrclib", action="store_true", help="Skip LRCLIB and transcribe with Faster Whisper")
    parser.add_argument("--whisper-model", default="large-v3", help="Faster Whisper model")
    parser.add_argument("--demucs-model", default="htdemucs_ft", help="Demucs separation model")
    parser.add_argument("--background-image", type=Path, help="Local image used as the video background")
    parser.add_argument("--background-color", help="Solid RGB background color")
    parser.add_argument("--visual-style", choices=VISUAL_STYLES, default=None)
    parser.add_argument("--background-style", choices=BACKGROUND_STYLES,
                        help="Procedural background saved for this project (default: fluid)")
    parser.add_argument("--cover", type=Path, help="Local artwork used for the procedural palette")
    parser.add_argument("--preset", choices=PRESETS, help="Appearance preset; explicit options override it")
    parser.add_argument("--resolution", choices=("1080p", "720p"), default="1080p")
    parser.add_argument("--cookies", type=Path, default=DEFAULT_COOKIES, help="Netscape cookies file for yt-dlp")
    parser.add_argument("--no-cookies", action="store_true", help="Do not upload or use a cookies file")
    parser.add_argument(
        "--logo",
        "--watermark",
        dest="logo",
        type=Path,
        default=DEFAULT_LOGO if DEFAULT_LOGO.is_file() else None,
        help="Local image file to overlay as a watermark or logo (default: logos/banner.png if present)",
    )
    parser.add_argument(
        "--no-logo",
        "--no-watermark",
        dest="no_logo",
        action="store_true",
        help="Do not include any logo or watermark overlay",
    )
    parser.add_argument(
        "--logo-position",
        dest="logo_position",
        choices=("top_left", "top_right", "bottom_left", "bottom_right"),
        default="top_left",
        help="Corner position for the watermark (default: top_left)",
    )
    parser.add_argument(
        "--logo-scale",
        dest="logo_scale",
        type=float,
        default=0.18,
        help="Watermark width relative to video canvas width (default: 0.18)",
    )
    parser.add_argument(
        "--logo-opacity",
        dest="logo_opacity",
        type=float,
        default=0.85,
        help="Watermark opacity from 0.0 to 1.0 (default: 0.85)",
    )
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs")
    parser.add_argument("--gpu", choices=("T4", "L4", "G4", "A100", "H100"), default="T4")
    parser.add_argument("--auth", choices=("oauth2", "adc"), default="oauth2")
    parser.add_argument("--timeout", type=int, default=14_400, help="Remote execution timeout in seconds")
    organize_help(parser)
    return parser


def build_render_parser() -> argparse.ArgumentParser:
    """Build the render-only Colab parser."""
    parser = argparse.ArgumentParser(
        prog="karaoke render",
        description="Render corrected lyrics from a prepared job folder without repeating preparation.",
    )
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Validate and show settings without starting Colab")
    parser.add_argument("--background-image", type=Path, help="Background image inside the project folder")
    parser.add_argument("--background-video", type=Path, help="Looping background video inside the project folder")
    parser.add_argument("--background-overlay-opacity", type=float, help="Dark overlay opacity (0–1)")
    parser.add_argument("--background-crop-right", type=float,
                        help="Fraction to crop from the right of an image/video (0–0.5)")
    parser.add_argument("--background-color", help="Solid RGB background color")
    parser.add_argument("--align", choices=("start", "center", "end"), help="Lyrics title and artist alignment")
    parser.add_argument("--graphic-style", choices=("default",))
    parser.add_argument("--theme", choices=(*THEMES, "even-better-lyrics-plus", "random", "job"), default="job",
                        help="Palette override; default: preserve the saved job background")
    parser.add_argument("--visual-style", choices=VISUAL_STYLES, help="Override the saved typography")
    parser.add_argument("--background-style", choices=BACKGROUND_STYLES, help="Override the saved background type")
    parser.add_argument("--cover", type=Path, help="Artwork palette for a procedural background")
    parser.add_argument("--seed", type=int, help="Reproducible cosmic background seed")
    parser.add_argument("--preset", choices=PRESETS, help="Appearance preset; explicit options override it")
    parser.add_argument("--title", help="Display title")
    parser.add_argument("--artist", help="Display artist")
    parser.add_argument("--resolution", choices=("1080p", "720p"), help="Video size")
    parser.add_argument("--fps", type=int, help="Frames per second (1–120)")
    parser.add_argument("--font-size", type=int, help="Lyric font size in pixels")
    parser.add_argument("--lyrics-active-color", help="Active lyric color, #RRGGBB")
    parser.add_argument("--lyrics-inactive-color", help="Inactive lyric color, #RRGGBB")
    parser.add_argument("--intro", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable/disable title intro")
    parser.add_argument("--intro-duration", type=float, help="Intro duration in seconds; exclusive with --intro-end")
    parser.add_argument("--intro-start", type=float, help="Intro start time in seconds (at least zero)")
    parser.add_argument("--intro-end", type=float, help="Intro end time in seconds; exclusive with --intro-duration")
    parser.add_argument("--thumbnail-time", type=float, help="Background time for the thumbnail, in seconds")
    parser.add_argument("--thumbnail-align", choices=("start", "center", "end"), help="Independent thumbnail alignment")
    parser.add_argument("--mode", choices=("both", "karaoke", "lyrics"), help="Default: saved project mode")
    parser.add_argument(
        "--logo",
        "--watermark",
        dest="logo",
        type=Path,
        default=None,
        help="Local image file to overlay as a watermark or logo",
    )
    parser.add_argument(
        "--no-logo",
        "--no-watermark",
        dest="no_logo",
        action="store_true",
        help="Do not include any logo or watermark overlay",
    )
    parser.add_argument(
        "--logo-position",
        dest="logo_position",
        choices=("top_left", "top_right", "bottom_left", "bottom_right"),
        default=None,
        help="Corner position for the watermark",
    )
    parser.add_argument(
        "--logo-scale",
        dest="logo_scale",
        type=float,
        default=None,
        help="Watermark width relative to video canvas width",
    )
    parser.add_argument(
        "--logo-opacity",
        dest="logo_opacity",
        type=float,
        default=None,
        help="Watermark opacity from 0.0 to 1.0",
    )
    parser.add_argument("--gpu", choices=("T4", "L4", "G4", "A100", "H100"), default="T4")
    parser.add_argument("--auth", choices=("oauth2", "adc"), default="oauth2")
    parser.add_argument("--timeout", type=int, default=14_400)
    organize_help(parser)
    return parser


def build_intro_parser() -> argparse.ArgumentParser:
    """Build the intro card generation parser."""
    parser = argparse.ArgumentParser(
        prog="karaoke intro",
        description="Generate the transparent title and artist intro card without a watermark.",
    )
    parser.add_argument("job_dir", type=Path, help="Path to prepared job directory")
    parser.add_argument("--mode", choices=("lyrics", "karaoke"), default="lyrics")
    parser.add_argument("--align", choices=("start", "center", "end"), help="Lyrics title and artist alignment")
    parser.add_argument("--graphic-style", choices=("default",))
    return parser


def run_intro(args: argparse.Namespace) -> Path:
    """Generate an unbranded intro card using the shared thumbnail typography."""
    from karaoke_app.intro_card import generate_intro_card_for_job

    root = args.job_dir.expanduser().resolve()
    result = generate_intro_card_for_job(root, mode=args.mode, align=getattr(args, "align", None),
                                         graphic_style=getattr(args, "graphic_style", None))
    if result is None:
        raise RuntimeError(f"Intro is disabled for {root}")
    LOGGER.info("Intro card created: %s", result)
    return result


def build_background_parser() -> argparse.ArgumentParser:
    """Build the standalone procedural background preview parser."""
    parser = argparse.ArgumentParser(prog="karaoke background", description="Preview a cosmic background locally.")
    parser.add_argument("config", type=Path, help="Project directory or standalone background JSON")
    parser.add_argument("--output", type=Path, default=Path("background-preview.mp4"))
    parser.add_argument("--duration", type=float, help="Seconds to preview (default: one complete loop)")
    parser.add_argument("--start", type=float, default=0, help="Starting time in the background animation")
    parser.add_argument("--width", type=int, help="Override video width for a faster preview")
    parser.add_argument("--height", type=int, help="Override video height for a faster preview")
    parser.add_argument("--fps", type=int, help="Override preview frames per second")
    return parser


def run_background(args: argparse.Namespace) -> Path:
    """Preview background configuration without audio, lyrics, or a Colab session."""
    from karaoke_app.cosmic_background import render_cosmic_video

    config_path = args.config.expanduser().resolve()
    if config_path.is_dir():
        from karaoke_app.job_document import STATE_FILENAME

        config_path /= STATE_FILENAME
    document = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Background configuration must be a JSON object")
    background = document.get("background", document)
    if not isinstance(background, dict) or background.get("kind") != "cosmic":
        raise ValueError('The background preview requires background.kind: "cosmic"')
    video = {"width": 1280, "height": 720, "fps": 24} | document.get("video", {})
    for key in ("width", "height", "fps"):
        if getattr(args, key) is not None:
            video[key] = getattr(args, key)
    if args.output.resolve() == config_path:
        raise ValueError("Preview output must not overwrite the configuration")
    result = render_cosmic_video(background, video, args.output, duration=args.duration, start=args.start)
    LOGGER.info("Background preview created: %s", result)
    return result



def show_commands() -> None:
    """Show the main workflow without overwhelming it with source-only flags."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Karaoke", show_header=False, box=None)
    for command, description in (
        ("source URL or FILE", "Prepare audio and timed lyrics"),
        ("configure PROJECT", "Edit sections, presets and output settings"),
        ("status PROJECT", "Show saved settings and available exports"),
        ("validate PROJECT", "Check files and lyrics before rendering"),
        ("render JOB --dry-run", "Validate files and review settings"),
        ("render JOB", "Render videos on Colab"),
        ("background JOB", "Preview the animated background"),
        ("preview JOB", "Preview timed lyrics locally"),
        ("thumbnail JOB / intro JOB", "Generate artwork"),
        ("cleanup JOB", "Inspect exports; move selected renders to recoverable trash"),
    ):
        table.add_row(command, description)
    console.print(table)
    console.print("Use karaoke COMMAND --help for options.")
    console.print('Example: uv run karaoke source "https://www.youtube.com/watch?v=VIDEO_ID"')

def main() -> int:
    """Run preparation, intro generation, or final render orchestration."""
    if not sys.argv[1:] or sys.argv[1:] in (["--help"], ["-h"]):
        show_commands()
        return 0
    verbose = "--verbose" in sys.argv[1:]
    if verbose:
        sys.argv[:] = [sys.argv[0], *(value for value in sys.argv[1:] if value != "--verbose")]
    log_path = configure_logging(verbose, diagnostics="--dry-run" not in sys.argv and
                                 "--help" not in sys.argv and "-h" not in sys.argv and
                                 sys.argv[1:2] not in (["cleanup"], ["status"], ["validate"]))
    if sys.argv[1:2] == ["source"]:
        del sys.argv[1]

    try:
        if sys.argv[1:2] == ["configure"]:
            from karaoke_app.visual_config import run_configure

            run_configure(sys.argv[2:])
        elif sys.argv[1:2] == ["preview"]:
            from karaoke_app.lyrics_preview import run_lyrics_preview

            run_lyrics_preview(sys.argv[2:])
        elif sys.argv[1:2] == ["cleanup"]:
            from karaoke_app.output_cleanup import run_cleanup

            run_cleanup(sys.argv[2:])
        elif sys.argv[1:2] in (["status"], ["validate"]):
            from karaoke_app.project_status import run_project_status

            run_project_status(sys.argv[1], sys.argv[2:])
        elif sys.argv[1:2] == ["thumbnail"]:
            from karaoke_app.thumbnail import run_thumbnail

            run_thumbnail(sys.argv[2:])
        elif sys.argv[1:2] == ["background"]:
            run_background(build_background_parser().parse_args(sys.argv[2:]))
        elif sys.argv[1:2] == ["render"]:
            args = build_render_parser().parse_args(sys.argv[2:])
            render_colab(args)
        elif sys.argv[1:2] == ["intro"]:
            args = build_intro_parser().parse_args(sys.argv[2:])
            run_intro(args)
        else:
            args = build_parser().parse_args()
            run_job(args)
    except KeyboardInterrupt:
        LOGGER.error("Interrupted")
        return 130
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, EOFError) as error:
        LOGGER.debug("Operation failed", exc_info=True)
        if isinstance(error, ProcessFailure):
            message = str(error)
        elif isinstance(error, subprocess.CalledProcessError):
            detail = failure_summary(error.stdout, error.stderr)
            message = f"External process failed (exit {error.returncode}).\n{detail}"
        else:
            message = str(error).splitlines()[0][:400] or type(error).__name__
        LOGGER.error("%s", message)
        if log_path:
            LOGGER.error("Diagnostics: %s", log_path)
        return 1
    finally:
        for handler in logging.getLogger().handlers:
            if hasattr(handler, "progress"):
                handler.close()
    return 0


def run_job(args: argparse.Namespace) -> Path:
    """Provision Colab, execute the media pipeline, and download its artifacts."""
    began = time.perf_counter()
    width, height = (1920, 1080) if args.resolution == "1080p" else (1280, 720)
    visual_defaults = preparation_visuals({"width": width, "height": height, "fps": 24}, args)
    _validate_installation()
    from karaoke_app.branding import store_shared_logo

    source_kind, source_value = _resolve_source(args.source)
    background_image = args.background_image.resolve() if args.background_image else None
    background_color = None if background_image else _normalize_color(args.background_color or "#0B1020")
    if background_image:
        _validate_image(background_image, "Background")
    if args.timeout <= 0:
        raise ValueError("Timeout must be positive")
    if args.lrclib_id is not None and (args.no_lrclib or args.lrclib_id <= 0):
        raise ValueError("LRCLIB ID must be positive and cannot be combined with --no-lrclib")
    from karaoke_app.lyric_references import plain_lines, validate_genius_url

    lyrics_text = args.lyrics_text.resolve() if args.lyrics_text else None
    if args.no_lrclib and (lyrics_text or args.genius_url):
        raise ValueError("--no-lrclib forces Whisper and cannot be combined with lyric references")
    if lyrics_text and not plain_lines(lyrics_text.read_text(encoding="utf-8-sig")):
        raise ValueError("Lyrics TXT contains no lyric lines")
    if args.genius_url:
        validate_genius_url(args.genius_url)
    for name, value, minimum, maximum in (
        ("Logo scale", args.logo_scale, 0.01, 0.5),
        ("Logo opacity", args.logo_opacity, 0.0, 1.0),
    ):
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")
    if getattr(args, "no_logo", False):
        logo_path = None
    else:
        logo_path = args.logo.resolve() if getattr(args, "logo", None) else None
        if not logo_path and DEFAULT_LOGO.is_file():
            logo_path = DEFAULT_LOGO
        if logo_path:
            _validate_image(logo_path, "Logo")

    shared_logo = store_shared_logo(logo_path) if logo_path else None

    cookies = None if args.no_cookies else args.cookies.resolve()
    if cookies and not cookies.is_file():
        if args.cookies != DEFAULT_COOKIES:
            LOGGER.warning("Requested cookies file not found; continuing without it: %s", cookies)
        cookies = None
    hf_token = _load_hf_token()

    now = datetime.now(UTC)
    job_id = f"karaoke-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    session = job_id
    output_dir = args.output_dir.resolve() / job_id
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    session_requested = False
    recovery_dir = output_dir.with_name(f"{job_id}.recovery")
    recovery = {
        "job_id": job_id,
        "session": session,
        "auth": args.auth,
        "remote_status_path": str(REMOTE_STATUS),
        "remote_archive_path": str(REMOTE_ARCHIVE),
        "session_stopped": False,
        "status": "incomplete",
    }
    succeeded = False

    with tempfile.TemporaryDirectory(prefix="karaoke-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        from karaoke_app.youtube_source import download_youtube, is_youtube_url

        source_metadata = None
        if source_kind == "url" and is_youtube_url(source_value):
            source_path, source_metadata = download_youtube(source_value, temporary_path / "youtube", cookies)
            source_kind, source_value = "file", str(source_path)
            cookies = None
        source_name = Path(source_value).stem if source_kind == "file" else None
        if source_kind == "file":
            from karaoke_app.media_transfer import prepare_audio_transfer

            source_value = str(prepare_audio_transfer(Path(source_value), temporary_path / "audio-transfer"))
        job_path = temporary_path / "job.json"
        archive_path = recovery_dir / "result.zip"
        status_path = recovery_dir / "status.json"
        hf_token_path = temporary_path / "hf_token"
        remote_source = source_value
        remote_background = None
        remote_cookies = None

        if source_kind == "file":
            source_path = Path(source_value)
            remote_source = f"/content/karaoke_source{source_path.suffix.lower()}"
        if background_image:
            remote_background = f"/content/karaoke_background{background_image.suffix.lower()}"
        if cookies:
            remote_cookies = "/content/karaoke_cookies.txt"

        job = {
            "schema_version": 1,
            "operation": "prepare",
            "source_bundle": str(REMOTE_SOURCE_BUNDLE),
            "job_id": job_id,
            "source": {
                "kind": source_kind,
                "value": remote_source,
                "name": source_name,
                "metadata": source_metadata,
            },
            "cookies_path": remote_cookies,
            "background": {
                "kind": "image" if remote_background else "solid",
                "value": remote_background or background_color,
                "overlay_opacity": 0,
            },
            "language": args.language,
            "lyrics": {
                "title": args.title,
                "artist": args.artist,
                "album": args.album,
                "lrclib_id": args.lrclib_id,
                "disable_lrclib": args.no_lrclib,
                "text_path": str(REMOTE_LYRICS_TEXT) if lyrics_text else None,
                "genius_url": args.genius_url,
            },
            "whisper_model": args.whisper_model,
            "demucs_model": args.demucs_model,
            "video": {"width": width, "height": height, "fps": 24},
            "archive_path": str(REMOTE_ARCHIVE),
        }
        if getattr(args, "no_logo", False):
            job["watermark"] = {"enabled": False}
        elif logo_path:
            job["watermark"] = {
                "enabled": True,
                "path": shared_logo,
                "position": args.logo_position,
                "scale": args.logo_scale,
                "margin": 0.05,
                "opacity": args.logo_opacity,
            }
        job.update(visual_defaults)
        job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
        if hf_token:
            hf_token_path.write_text(hf_token, encoding="utf-8")

        source_bundle = temporary_path / "source-job.zip"
        resources = {
            Path('/content/karaoke_pipeline.py'): COLAB_SCRIPT,
            Path("/content/karaoke_ass.py"): ASS_MODULE,
            REMOTE_LYRICS_MODULE: LYRICS_MODULE,
            REMOTE_REFERENCES_MODULE: REFERENCES_MODULE,
            Path("/content/karaoke_song_identity.py"): PACKAGE_ROOT / "song_identity.py",
        }
        if source_kind == "file":
            resources[Path(remote_source)] = Path(source_value)
        if background_image:
            resources[Path(remote_background)] = background_image
        if lyrics_text:
            resources[REMOTE_LYRICS_TEXT] = lyrics_text
        from dotenv import load_dotenv

        from karaoke_app.lyric_references import prefetch_genius_reference

        load_dotenv(PROJECT_ROOT / ".env", override=False)
        prefetch_visible = not args.no_lrclib and bool(args.title or args.artist or args.genius_url)
        if prefetch_visible:
            notify("Checking lyric references", stage="reference_prefetch")
        try:
            local_reference = prefetch_genius_reference(
                job["lyrics"], {"title": args.title, "artist": args.artist}, COLAB_SCRIPT,
            )
        finally:
            if prefetch_visible:
                notify("Checking lyric references", stage="reference_prefetch", state="stopped")
        if local_reference:
            reference_path = temporary_path / "genius_reference.json"
            reference_path.write_text(json.dumps(local_reference, ensure_ascii=False), encoding="utf-8")
            resources[REMOTE_GENIUS_REFERENCE] = reference_path
            job["lyrics"]["genius_reference_path"] = str(REMOTE_GENIUS_REFERENCE)
            job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
            LOGGER.debug("Local Genius fallback ready for acoustic alignment; LRCLIB keeps priority")
        _create_source_bundle(resources, source_bundle)
        warn_large_upload(source_bundle)

        recovery_dir.mkdir()
        notify("Preparing render", stage="local_render", state="stopped")
        colab = ["colab", f"--auth={args.auth}"]
        try:
            notify("Preparing Colab", stage="colab_setup")
            session_requested = True
            _run([*colab, "new", "--session", session, "--gpu", args.gpu])
            _upload(colab, session, job_path, REMOTE_JOB)
            _upload(colab, session, source_bundle, REMOTE_SOURCE_BUNDLE)
            if cookies:
                _upload(colab, session, cookies, Path(remote_cookies))
            if hf_token:
                _upload(colab, session, hf_token_path, REMOTE_HF_TOKEN)
            _run([*colab, "install", "--session", session, "--requirement", str(COLAB_REQUIREMENTS)])
            exec_error = None
            try:
                exec_res = _run(
                    [*colab, "exec", "--session", session, "--file",
                     str(COLAB_SCRIPT.with_name("karaoke_launch.py")), "--timeout", str(args.timeout)],
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as failure:
                exec_res = None
                exec_error = failure

            status_error = None
            try:
                _download_with_retry(colab, session, REMOTE_STATUS, status_path)
                status = json.loads(status_path.read_text(encoding="utf-8"))
                recovery["remote_status"] = status
            except Exception as failure:
                status = {}
                status_error = failure

            if status_error is not None and exec_error is None:
                raise status_error

            if exec_error is not None or (exec_res and exec_res.returncode != 0) or status.get("status") != "completed":
                try:
                    _download_with_retry(colab, session, REMOTE_ARCHIVE, archive_path)
                except Exception:
                    pass
                if status.get("stage") == "lyrics" and status.get("recovery_archive_path"):
                    recovery["remote_recovery_archive_path"] = status["recovery_archive_path"]
                    try:
                        _download_with_retry(
                            colab, session, Path(status["recovery_archive_path"]), recovery_dir / "checkpoint.zip"
                        )
                    except Exception as failure:
                        recovery["checkpoint_download_error"] = str(failure)
                if exec_error is not None:
                    raise RuntimeError(f"Remote execution failed: {exec_error}") from exec_error
                if status_error is not None:
                    raise status_error
                fallback = f"exit code {exec_res.returncode if exec_res else 'unknown'}"
                err = status.get("error_summary") or status.get("error", fallback)
                raise RuntimeError(f"{status.get('stage', 'remote')}: {err}")
            _download_with_retry(colab, session, REMOTE_ARCHIVE, archive_path)
            try:
                _extract_archive(archive_path, output_dir)
                succeeded = True
            except Exception as exc:
                raise RuntimeError(f"{exc}; recovery manifest at {recovery_dir / 'recovery.json'}") from exc
        except BaseException as err:
            if not succeeded:
                if session_requested:
                    recovery["session_stopped"] = _stop_session(colab, session)
                recovery["status"] = "cancelled" if isinstance(err, KeyboardInterrupt | SystemExit) else "failed"
                recovery["error"] = f"{type(err).__name__}: {err}"
                recovery["local_artifacts"] = [p.name for p in recovery_dir.iterdir()]
                (recovery_dir / "recovery.json").write_text(json.dumps(recovery, indent=2), encoding="utf-8")
                if not recovery.get("session_stopped", False) and session_requested:
                    raise RuntimeError("Session stop was not confirmed; session may still be running") from err
                if not isinstance(err, RuntimeError | KeyboardInterrupt | SystemExit):
                    raise RuntimeError(f"{err}; recovery manifest at {recovery_dir / 'recovery.json'}") from err
            raise
        finally:
            if session_requested and succeeded:
                stopped = _stop_session(colab, session)
                if not stopped:
                    recovery["session_stopped"] = False
                    recovery["local_artifacts"] = [p.name for p in recovery_dir.iterdir()]
                    (recovery_dir / "recovery.json").write_text(json.dumps(recovery, indent=2), encoding="utf-8")
                    raise RuntimeError("Session stop was not confirmed; session may still be running")
                shutil.rmtree(recovery_dir, ignore_errors=True)

    if not args.no_lrclib:
        from dotenv import load_dotenv

        from karaoke_app.lyric_repair import repair_prepared_lyrics

        load_dotenv(PROJECT_ROOT / ".env", override=False)
        notify("Checking prepared lyrics", stage="review")
        try:
            repair = repair_prepared_lyrics(output_dir, COLAB_SCRIPT, genius_url=args.genius_url)
            LOGGER.debug("Local lyric reference recovery: %s", repair)
            if repair.get("estimated_words"):
                LOGGER.info(
                    "Reference text applied; %s word timings estimated. Optional acoustic realignment: %s",
                    repair["estimated_words"], repair.get("realign_hint"),
                )
        except Exception as error:
            LOGGER.warning(
                "Local lyric reference recovery failed (%s); keeping prepared artifacts", type(error).__name__,
            )
        finally:
            notify("Checking prepared lyrics", stage="review", state="stopped")

    _report_lyrics_review(output_dir)
    _save_client_performance(output_dir, began, args.gpu)
    LOGGER.info("Completed in %.1fs", time.perf_counter() - began)
    LOGGER.info("Artifacts saved to %s", output_dir)
    LOGGER.info("To render final videos on Colab, run:")
    LOGGER.info("uv run karaoke render %s", output_dir)
    return output_dir



def _report_lyrics_review(root: Path) -> None:
    """Report unresolved review needs after all local recovery has finished."""
    path = root / "lyrics_validation.json"
    if not path.is_file():
        LOGGER.warning("Lyrics validation unavailable. Review the prepared lyrics before rendering.")
        return
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        LOGGER.warning("Lyrics validation unreadable. Review the prepared lyrics before rendering: %s", path)
        return
    if report.get("needs_review"):
        count = sum(bool(line.get("needs_review")) for line in report.get("lines", []))
        detail = f"{count} flagged line{'s' if count != 1 else ''}" if count else "validation incomplete"
        LOGGER.warning("Lyrics need review (%s): %s", detail, path)

def render_colab(args: argparse.Namespace) -> Path:
    """Validate lyrics locally and render the prepared job on Colab."""
    began = time.perf_counter()
    if args.timeout <= 0:
        raise ValueError("Timeout must be positive")
    from karaoke_app.rendering import prepare_render, render_subtitles
    from karaoke_app.visual_config import show_appearance

    root = args.job_dir.expanduser().resolve()
    request = prepare_render(root, vars(args), report=show_appearance)
    document, selected_theme, args.mode = request.document, request.theme, request.mode
    if getattr(args, "dry_run", False):
        LOGGER.info("Validation passed · mode: %s · no files changed; Colab not started", args.mode)
        return root
    _validate_installation()
    notify("Preparing render", stage="local_render")
    subtitles = render_subtitles(request)
    transcript, ass_by_mode, srt_content = subtitles.transcript, subtitles.ass_by_mode, subtitles.srt
    render_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{args.mode}-{uuid.uuid4().hex[:12]}"
    output_dir = root / "renders" / render_id
    session = f"render-{uuid.uuid4().hex[:10]}"
    session_requested = False

    with tempfile.TemporaryDirectory(prefix="karaoke-render-") as temporary_directory:
        temporary = Path(temporary_directory)
        bundle_path = temporary / "render-job.zip"
        config_path = temporary / "job.json"
        archive_path = temporary / "result.zip"
        status_path = temporary / "status.json"
        _create_render_bundle(
            root,
            document,
            args.mode,
            ass_by_mode,
            bundle_path,
            transcript=transcript,
            srt_content=srt_content,
        )
        warn_large_upload(bundle_path)
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "operation": "render",
                    "mode": args.mode,
                    "theme": selected_theme,
                    "archive_path": str(REMOTE_ARCHIVE),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        notify("Preparing render", stage="local_render", state="stopped")
        colab = ["colab", f"--auth={args.auth}"]
        try:
            notify("Preparing Colab", stage="colab_setup")
            session_requested = True
            _run([*colab, "new", "--session", session, "--gpu", args.gpu])
            _upload(colab, session, config_path, REMOTE_JOB)
            _upload(colab, session, bundle_path, REMOTE_RENDER_JOB)
            _run(
                [
                    *colab,
                    "exec",
                    "--session",
                    session,
                    "--file",
                    str(COLAB_SCRIPT),
                    "--timeout",
                    str(args.timeout),
                ]
            )
            _download_with_retry(colab, session, REMOTE_STATUS, status_path)
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("status") != "completed":
                detail = status.get("error_summary") or status.get("error", "unknown error")
                raise RuntimeError(f"Remote render failed: {detail}")
            _download_with_retry(colab, session, REMOTE_ARCHIVE, archive_path)
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            _extract_archive(archive_path, output_dir)
            output_subtitles = output_dir / "subtitles"
            output_subtitles.mkdir(parents=True, exist_ok=True)
            safe_title = _safe_filename(str(document.get("title") or "lyrics"))
            (output_subtitles / f"{safe_title}.srt").write_text(srt_content, encoding="utf-8")
        finally:
            if session_requested and not _stop_session(colab, session):
                raise RuntimeError(f"Session stop was not confirmed; stop {session} manually")

    _save_client_performance(output_dir, began, args.gpu)
    LOGGER.info("Completed in %.1fs", time.perf_counter() - began)
    LOGGER.info("Rendered artifacts saved to %s", output_dir)
    return output_dir


def _save_client_performance(output_dir: Path, began: float, gpu: str) -> None:
    path = output_dir / "performance.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    report.update(client_elapsed_seconds=time.perf_counter() - began, gpu_requested=gpu)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _create_source_bundle(resources: dict[Path, Path], destination: Path) -> None:
    """Batch non-secret source inputs into one upload, retaining remote filenames."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for remote, local in resources.items():
            archive.write(local, remote.relative_to("/content").as_posix())


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return normalized[:80] or "karaoke"


def _validate_installation() -> None:
    if not shutil.which("colab"):
        raise OSError("The 'colab' executable is not available. Run 'uv sync --dev' to install project dependencies.")
    if not all(path.is_file() for path in (
        COLAB_SCRIPT, COLAB_SCRIPT.with_name("karaoke_launch.py"), COLAB_REQUIREMENTS,
        ASS_MODULE, LYRICS_MODULE, REFERENCES_MODULE,
    )):
        raise OSError("Colab pipeline files are missing from the project")


def _resolve_source(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        hostname = (parsed.hostname or "").lower()
        if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            normalized_value = value.replace(r"\?", "?").replace(r"\=", "=").replace(r"\&", "&")
            if "\\" in normalized_value:
                raise ValueError(
                    "Invalid YouTube URL: unexpected backslash. Use https://www.youtube.com/watch?v=VIDEO_ID"
                )
            parsed = urlparse(normalized_value)
            if parsed.path.rstrip("/") == "/watch" and not parse_qs(parsed.query).get("v"):
                raise ValueError(
                    "Invalid YouTube watch URL: missing the 'v=' parameter. "
                    "Use https://www.youtube.com/watch?v=VIDEO_ID"
                )
            return "url", normalized_value
        return "url", value
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Source file not found: {path}")
    return "file", str(path)


def _normalize_color(value: str) -> str:
    color = value.strip()
    if not color.startswith("#"):
        color = f"#{color}"
    if not COLOR_PATTERN.match(color):
        raise ValueError(f"Invalid color format: {value}. Use #RRGGBB.")
    return color.upper()


def _load_hf_token() -> str | None:
    token = os.environ.get("HF_TOKEN")
    if token and token.strip():
        return token.strip()
    env_path = PROJECT_ROOT / ".env"
    if env_path.is_file():
        values = dotenv_values(env_path)
        candidate = values.get("HF_TOKEN")
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def _upload(colab: list[str], session: str, local_path: Path, remote_path: Path) -> None:
    LOGGER.info("Uploading to Colab (%s)", upload_size(local_path))
    try:
        _run([*colab, "upload", "--session", session, str(local_path), str(remote_path)])
    except ProcessFailure as exc:
        raise RuntimeError(upload_failure_message(local_path, str(exc))) from exc


def _extract_archive(archive_path: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".karaoke-extract-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "artifacts"
        staging.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                target = (staging / member.filename).resolve()
                if not target.is_relative_to(staging.resolve()) or (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError(f"Unsafe archive member: {member.filename}")
            archive.extractall(staging)
        staging.rename(destination)


def _validate_image(path: Path, label: str) -> None:
    from PIL import Image

    try:
        with Image.open(path) as image:
            image.load()
    except (OSError, ValueError) as error:
        raise ValueError(f"{label} image is not decodable: {path}") from error


def _download_with_retry(colab: list[str], session: str, remote: Path, local: Path) -> None:
    """Publish only a completed download, retaining partial bytes for diagnosis."""
    partial = local.with_suffix(f"{local.suffix}.partial")
    error = "no file downloaded"
    for attempt in range(3):
        try:
            if partial.exists():
                partial.replace(local.with_suffix(f"{local.suffix}.attempt-{attempt}.partial"))
            result = _run(
                [*colab, "download", "--session", session, str(remote), str(partial)], check=False, timeout=300
            )
            if result.returncode == 0 and partial.is_file():
                partial.replace(local)
                return
            error = f"exit code {result.returncode}: {failure_summary(result.stdout, result.stderr)}"
        except (OSError, subprocess.SubprocessError) as failure:
            error = str(failure)
    raise RuntimeError(f"Could not download {remote} after 3 attempts: {error}")


def _stop_session(colab: list[str], session: str) -> bool:
    try:
        result = _run([*colab, "stop", "--session", session], check=False, timeout=60)
        if result.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError) as error:
        LOGGER.debug("Could not stop session %s: %s", session, error)
    LOGGER.error("Session %s may still be running; stop it manually", session)
    return False


def _run(
    command: list[str], *, check: bool = True, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return run_process(command, check=check, timeout=timeout)


if __name__ == "__main__":
    sys.exit(main())

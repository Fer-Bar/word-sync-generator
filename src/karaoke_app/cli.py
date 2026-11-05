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
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values

from karaoke_app.themes import THEMES, apply_render_theme
from karaoke_app.visual_config import BACKGROUND_STYLES, VISUAL_STYLES, apply_visual_options, preparation_visuals

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
COLAB_SCRIPT = PROJECT_ROOT / "colab" / "karaoke_job.py"
ASS_MODULE = PROJECT_ROOT / "src" / "karaoke_app" / "ass.py"
LYRICS_MODULE = PROJECT_ROOT / "src" / "karaoke_app" / "lyrics_file.py"
REFERENCES_MODULE = PROJECT_ROOT / "src" / "karaoke_app" / "lyric_references.py"
COSMIC_MODULE = PROJECT_ROOT / "src" / "karaoke_app" / "cosmic_background.py"
COLAB_REQUIREMENTS = PROJECT_ROOT / "colab" / "requirements.txt"
DEFAULT_COOKIES = PROJECT_ROOT / "cookies.txt"
DEFAULT_LOGO = PROJECT_ROOT / "logos" / "banner.png"
REMOTE_JOB = Path("/content/karaoke_job.json")
REMOTE_ARCHIVE = Path("/content/karaoke_result.zip")
REMOTE_STATUS = Path("/content/karaoke_status.json")
REMOTE_HF_TOKEN = Path("/content/.hf_token")
REMOTE_LYRICS_MODULE = Path("/content/karaoke_lyrics_file.py")
REMOTE_REFERENCES_MODULE = Path("/content/karaoke_lyric_references.py")
REMOTE_LYRICS_TEXT = Path("/content/lyrics_reference.txt")
REMOTE_RENDER_JOB = Path("/content/karaoke_render_job.zip")
COLOR_PATTERN = re.compile(r"^#?[0-9a-fA-F]{6}$")


def build_parser() -> argparse.ArgumentParser:
    """Build the preparation command parser."""
    parser = argparse.ArgumentParser(description="Prepare a durable karaoke job on Google Colab.")
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
    parser.add_argument("--visual-style", choices=VISUAL_STYLES, default="plus")
    parser.add_argument("--background-style", choices=BACKGROUND_STYLES,
                        help="Procedural background saved in job.json (default: fluid)")
    parser.add_argument("--cover", type=Path, help="Local artwork used for the procedural palette")
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
    return parser


def build_render_parser() -> argparse.ArgumentParser:
    """Build the render-only Colab parser."""
    parser = argparse.ArgumentParser(
        prog="karaoke render",
        description="Render corrected lyrics from a prepared job folder without repeating preparation.",
    )
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--align", choices=("start", "center", "end"), help="Lyrics title and artist alignment")
    parser.add_argument("--graphic-style", choices=("default", "fomo", "fomo-xerox"))
    parser.add_argument("--graphic-palette", choices=("light", "dark"))
    parser.add_argument("--title-layout", choices=("stacked", "wide"))
    parser.add_argument("--theme", choices=(*THEMES, "even-better-lyrics-plus", "random", "job"), default="job",
                        help="Palette override; default: preserve the saved job background")
    parser.add_argument("--visual-style", choices=VISUAL_STYLES, help="Override the saved typography")
    parser.add_argument("--background-style", choices=BACKGROUND_STYLES, help="Override the saved background type")
    parser.add_argument("--cover", type=Path, help="Artwork palette for a procedural background")
    parser.add_argument("--seed", type=int, help="Reproducible cosmic background seed")
    parser.add_argument("--mode", choices=("both", "karaoke", "lyrics"), default="both")
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
    return parser


def build_editor_parser() -> argparse.ArgumentParser:
    """Build the local style editor parser."""
    parser = argparse.ArgumentParser(
        prog="karaoke editor",
        description="Launch the local live style editor to customize fonts, colors, and layout before rendering.",
    )
    parser.add_argument("job_dir", type=Path, help="Path to prepared job directory")
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open web browser automatically")
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
    parser.add_argument("--graphic-style", choices=("default", "fomo", "fomo-xerox"))
    parser.add_argument("--graphic-palette", choices=("light", "dark"))
    parser.add_argument("--title-layout", choices=("stacked", "wide"))
    return parser


def run_intro(args: argparse.Namespace) -> Path:
    """Generate an unbranded intro card using the shared thumbnail typography."""
    from karaoke_app.intro_card import generate_intro_card_for_job

    root = args.job_dir.expanduser().resolve()
    result = generate_intro_card_for_job(root, mode=args.mode, align=getattr(args, "align", None),
                                         graphic_style=getattr(args, "graphic_style", None),
                                         graphic_palette=getattr(args, "graphic_palette", None),
                                         title_layout=getattr(args, "title_layout", None))
    if result is None:
        raise RuntimeError(f"Intro is disabled for {root}")
    LOGGER.info("Intro card created: %s", result)
    return result


def build_background_parser() -> argparse.ArgumentParser:
    """Build the standalone procedural background preview parser."""
    parser = argparse.ArgumentParser(prog="karaoke background", description="Preview a cosmic background locally.")
    parser.add_argument("config", type=Path, help="Job directory, job.json, or standalone background JSON")
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
        config_path /= "job.json"
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


def main() -> int:
    """Run preparation, style editor, intro generation, or final render orchestration."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        if sys.argv[1:2] == ["configure"]:
            from karaoke_app.visual_config import run_configure

            run_configure(sys.argv[2:])
        elif sys.argv[1:2] == ["preview"]:
            from karaoke_app.lyrics_preview import run_lyrics_preview

            run_lyrics_preview(sys.argv[2:])
        elif sys.argv[1:2] == ["migrate"]:
            from karaoke_app.migration import run_migration

            run_migration(sys.argv[2:])
        elif sys.argv[1:2] == ["thumbnail"]:
            from karaoke_app.thumbnail import run_thumbnail

            run_thumbnail(sys.argv[2:])
        elif sys.argv[1:2] == ["background"]:
            run_background(build_background_parser().parse_args(sys.argv[2:]))
        elif sys.argv[1:2] == ["render"]:
            args = build_render_parser().parse_args(sys.argv[2:])
            render_colab(args)
        elif sys.argv[1:2] == ["editor"]:
            args = build_editor_parser().parse_args(sys.argv[2:])
            launch_editor(args)
        elif sys.argv[1:2] == ["intro"]:
            args = build_intro_parser().parse_args(sys.argv[2:])
            run_intro(args)
        else:
            args = build_parser().parse_args()
            run_job(args)
    except KeyboardInterrupt:
        LOGGER.error("Interrupted")
        return 130
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        LOGGER.error("%s", error)
        return 1
    return 0


def launch_editor(args: argparse.Namespace) -> None:
    """Launch the local style editor."""
    from karaoke_app.editor import run_editor_server

    run_editor_server(args.job_dir, port=args.port, open_browser=not args.no_browser)


def run_job(args: argparse.Namespace) -> Path:
    """Provision Colab, execute the media pipeline, and download its artifacts."""
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
        LOGGER.warning("Cookies file not found; continuing without cookies: %s", cookies)
        cookies = None
    hf_token = _load_hf_token()

    now = datetime.now(UTC)
    job_id = f"karaoke-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    session = job_id
    output_dir = args.output_dir.resolve() / job_id
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    session_created = False
    recovery_dir = output_dir.with_name(f"{job_id}.recovery")
    recovery_dir.mkdir()
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

        width, height = (1920, 1080) if args.resolution == "1080p" else (1280, 720)
        job = {
            "schema_version": 1,
            "operation": "prepare",
            "job_id": job_id,
            "source": {
                "kind": source_kind,
                "value": remote_source,
                "name": Path(source_value).stem if source_kind == "file" else None,
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

        colab = ["colab", f"--auth={args.auth}"]
        try:
            _run([*colab, "new", "--session", session, "--gpu", args.gpu])
            session_created = True
            _upload(colab, session, job_path, REMOTE_JOB)
            if source_kind == "file":
                _upload(colab, session, Path(source_value), Path(remote_source))
            if background_image:
                _upload(colab, session, background_image, Path(remote_background))
            if cookies:
                _upload(colab, session, cookies, Path(remote_cookies))
            if hf_token:
                _upload(colab, session, hf_token_path, REMOTE_HF_TOKEN)
            _upload(colab, session, ASS_MODULE, Path("/content/karaoke_ass.py"))
            _upload(colab, session, LYRICS_MODULE, REMOTE_LYRICS_MODULE)
            _upload(colab, session, REFERENCES_MODULE, REMOTE_REFERENCES_MODULE)
            if lyrics_text:
                _upload(colab, session, lyrics_text, REMOTE_LYRICS_TEXT)
            _run([*colab, "install", "--session", session, "--requirement", str(COLAB_REQUIREMENTS)])
            exec_error = None
            try:
                exec_res = _run(
                    [*colab, "exec", "--session", session, "--file", str(COLAB_SCRIPT), "--timeout", str(args.timeout)],
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
                err = status.get("error", f"exit code {exec_res.returncode if exec_res else 'unknown'}")
                raise RuntimeError(f"{status.get('stage', 'remote')}: {err}")
            _download_with_retry(colab, session, REMOTE_ARCHIVE, archive_path)
            try:
                _extract_archive(archive_path, output_dir)
                succeeded = True
            except Exception as exc:
                raise RuntimeError(f"{exc}; recovery manifest at {recovery_dir / 'recovery.json'}") from exc
        except Exception as err:
            if not succeeded:
                if session_created:
                    recovery["session_stopped"] = _stop_session(colab, session)
                recovery["local_artifacts"] = [p.name for p in recovery_dir.iterdir()]
                (recovery_dir / "recovery.json").write_text(json.dumps(recovery, indent=2), encoding="utf-8")
                if not recovery.get("session_stopped", False) and session_created:
                    raise RuntimeError("Session stop was not confirmed; session may still be running") from err
                if not isinstance(err, RuntimeError):
                    raise RuntimeError(f"{err}; recovery manifest at {recovery_dir / 'recovery.json'}") from err
                raise
        finally:
            if session_created and succeeded:
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
        try:
            repair = repair_prepared_lyrics(output_dir, COLAB_SCRIPT, genius_url=args.genius_url)
            LOGGER.info("Local lyric reference recovery: %s", repair)
            if repair.get("estimated_words"):
                LOGGER.info(
                    "Reference text applied; %s word timings estimated. Optional acoustic realignment: %s",
                    repair["estimated_words"], repair.get("realign_hint"),
                )
        except Exception as error:
            LOGGER.warning(
                "Local lyric reference recovery failed (%s); keeping prepared artifacts", type(error).__name__,
            )

    LOGGER.info("Artifacts saved to %s", output_dir)
    LOGGER.info("To customize fonts, colors, and preview in real-time, run:")
    LOGGER.info("uv run karaoke editor %s", output_dir)
    LOGGER.info("To render final videos on Colab, run:")
    LOGGER.info("uv run karaoke render %s", output_dir)
    return output_dir


def render_colab(args: argparse.Namespace) -> Path:
    """Validate lyrics locally and run only FFmpeg rendering on Colab."""
    from karaoke_app.ass import generate_ass
    from karaoke_app.branding import store_shared_logo
    from karaoke_app.job_document import load_job_document, resolve_job_asset
    from karaoke_app.lyrics_file import load_lyrics_file, lyrics_to_transcript
    from karaoke_app.style import StyleConfig

    _validate_installation()
    root = args.job_dir.expanduser().resolve()
    document, selected_theme = apply_render_theme(load_job_document(root), getattr(args, "theme", "job"))
    document = apply_visual_options(
        document, visual_style=getattr(args, "visual_style", None),
        background_style=getattr(args, "background_style", None), cover=getattr(args, "cover", None),
    )
    if getattr(args, "seed", None) is not None:
        document, _ = apply_render_theme(document, "job", args.seed)
    LOGGER.info("Render theme: %s; background seed: %s", selected_theme, document["background"].get("seed", "n/a"))
    if getattr(args, "no_logo", False):
        document["watermark"] = {"enabled": False}
    elif getattr(args, "logo", None):
        logo_path = args.logo.resolve()
        if not logo_path.is_file():
            raise FileNotFoundError(f"Logo not found: {logo_path}")
        document["watermark"] = {
            "enabled": True,
            "path": store_shared_logo(logo_path),
            "position": getattr(args, "logo_position", None) or "top_left",
            "scale": getattr(args, "logo_scale", None) or 0.18,
            "margin": 0.05,
            "opacity": 0.85,
        }
    watermark = document.get("watermark") or {"enabled": False}
    if watermark.get("enabled", True):
        from karaoke_app.job_document import resolve_watermark_path

        watermark["path"] = store_shared_logo(resolve_watermark_path(root, watermark.get("path")))
        for name in ("position", "scale", "opacity"):
            override = getattr(args, f"logo_{name}", None)
            if override is not None:
                watermark[name] = override
        document["watermark"] = watermark
    from karaoke_app.fomo import apply_graphic_options
    from karaoke_app.job_document import validate_job_document
    from karaoke_app.srt import generate_srt

    document = apply_graphic_options(document, graphic_style=getattr(args, "graphic_style", None),
                                         graphic_palette=getattr(args, "graphic_palette", None),
                                     title_layout=getattr(args, "title_layout", None),
                                     align=getattr(args, "align", None))
    if (document.get("watermark") or {}).get("enabled", False):
        for name in ("position", "scale", "opacity"):
            override = getattr(args, f"logo_{name}", None)
            if override is not None:
                document["watermark"][name] = override
    document = validate_job_document(document)

    lyrics_path = resolve_job_asset(root, document["media"]["lyrics"], "lyrics")
    lyrics = load_lyrics_file(lyrics_path, require_words=True)
    transcript = lyrics_to_transcript(lyrics)
    srt_content = generate_srt(transcript)

    modes = ("karaoke", "lyrics") if args.mode == "both" else (args.mode,)
    style_config = (
        StyleConfig.from_dict(document.get("style"), height=document["video"]["height"])
        if document.get("style")
        else None
    )
    ass_by_mode = {
        mode: generate_ass(
            transcript,
            document["video"],
            style=style_config,
            mode=mode,
        )
        for mode in modes
    }
    render_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{args.mode}"
    output_dir = root / "renders" / render_id
    session = f"render-{uuid.uuid4().hex[:10]}"
    session_created = False

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
        colab = ["colab", f"--auth={args.auth}"]
        try:
            _run([*colab, "new", "--session", session, "--gpu", args.gpu])
            session_created = True
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
            _run([*colab, "download", "--session", session, str(REMOTE_STATUS), str(status_path)])
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("status") != "completed":
                raise RuntimeError(f"Remote render failed: {status.get('error', 'unknown error')}")
            _run([*colab, "download", "--session", session, str(REMOTE_ARCHIVE), str(archive_path)])
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            _extract_archive(archive_path, output_dir)
            output_subtitles = output_dir / "subtitles"
            output_subtitles.mkdir(parents=True, exist_ok=True)
            safe_title = _safe_filename(str(document.get("title") or "lyrics"))
            (output_subtitles / f"{safe_title}.srt").write_text(srt_content, encoding="utf-8")
        finally:
            if session_created:
                _run([*colab, "stop", "--session", session], check=False)

    LOGGER.info("Rendered artifacts saved to %s", output_dir)
    return output_dir


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return normalized[:80] or "karaoke"


def _create_render_bundle(
    job_dir: Path,
    document: dict[str, object],
    mode: str,
    ass_by_mode: dict[str, str],
    destination: Path,
    transcript: dict[str, Any] | None = None,
    srt_content: str | None = None,
) -> None:
    from karaoke_app.job_document import resolve_job_asset, resolve_watermark_path
    from karaoke_app.render_graphics import generate_render_graphics

    media = document["media"]
    if not isinstance(media, dict):
        raise ValueError("Invalid job media configuration")
    modes = ("karaoke", "lyrics") if mode == "both" else (mode,)
    audio_keys = {"karaoke": "instrumental_audio", "lyrics": "original_audio"}
    required = {str(media[audio_keys[item]]) for item in modes}
    background = document["background"]
    if isinstance(background, dict) and background.get("kind") in {"image", "video"}:
        required.add(str(background["path"]))

    bundle_document = json.loads(json.dumps(document))
    watermark = bundle_document.get("watermark")
    watermark_file: Path | None = None
    if isinstance(watermark, dict) and watermark.get("enabled", True):
        watermark_file = resolve_watermark_path(job_dir, watermark.get("path"))
        bundle_wm_name = f"watermark{watermark_file.suffix.lower()}"
        watermark["path"] = bundle_wm_name

    with tempfile.TemporaryDirectory(prefix="render-graphics-") as graphics_directory:
        graphics = Path(graphics_directory)
        timing = generate_render_graphics(job_dir, document, modes, graphics, transcript)
        if watermark_file is not None and (document.get("intro") or {}).get("graphic_style") in ("fomo", "fomo-xerox"):
            from karaoke_app.fomo import fomo_logo

            prepared_logo = Path(graphics_directory) / "fomo-watermark.png"
            fomo_logo(watermark_file, palette=(document.get("intro") or {}).get("graphic_palette", "light")).save(
                prepared_logo)
            watermark_file = prepared_logo
            bundle_document["watermark"]["path"] = "watermark.png"
        if (document.get("intro") or {}).get("graphic_style") == "fomo-xerox":
            bundle_document["background"] = {"kind": "image", "path": "graphics/background.png",
                                             "overlay_opacity": 0}
        bundle_document["intro"] = timing or {"enabled": False}
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("job.json", json.dumps(bundle_document, ensure_ascii=False, indent=2) + "\n")
            if background.get("kind") == "cosmic":
                if not COSMIC_MODULE.is_file():
                    raise FileNotFoundError(f"Missing cosmic background generator module: {COSMIC_MODULE}")
                archive.write(COSMIC_MODULE, "cosmic_background.py")
            if (document.get("style") or {}).get("lyrics_effect") == "word-synced":
                from karaoke_app.lyrics_plus import switzer_font

                font = switzer_font()
                archive.write(font, f"fonts/{font.name}")
                archive.write(font.with_name("Switzer-FFL.txt"), "fonts/Switzer-FFL.txt")
                from karaoke_app.browser_lyrics import ASSETS, build_browser_scene

                if transcript is None:
                    raise ValueError("Plus rendering requires the timed transcript")
                archive.write(PROJECT_ROOT / "src/karaoke_app/browser_lyrics.py", "browser_lyrics.py")
                for asset_root in (ASSETS / "braccato", ASSETS / "browser_lyrics"):
                    for asset in sorted(asset_root.rglob("*")):
                        if asset.is_file():
                            archive.write(asset, f"browser_assets/{asset.relative_to(ASSETS).as_posix()}")
                for item in modes:
                    scene = build_browser_scene(transcript, document["video"], document["style"], item)
                    archive.writestr(f"{item}.scene.json", json.dumps(scene, ensure_ascii=False))
            if srt_content:
                archive.writestr("lyrics.srt", srt_content)
            elif (job_dir / "lyrics.srt").is_file():
                archive.write(job_dir / "lyrics.srt", "lyrics.srt")
            for item in modes:
                archive.writestr(f"{item}.ass", ass_by_mode[item])
            for relative_path in sorted(required):
                path = resolve_job_asset(job_dir, relative_path, relative_path)
                archive.write(path, relative_path)
            if watermark_file is not None:
                archive.write(watermark_file, bundle_document["watermark"]["path"])
            for graphic in sorted(graphics.rglob("*.png")):
                archive.write(graphic, f"graphics/{graphic.relative_to(graphics).as_posix()}")


def _validate_installation() -> None:
    if not shutil.which("colab"):
        raise OSError("The 'colab' executable is not available. Run 'uv sync --dev' to install project dependencies.")
    if not all(path.is_file() for path in (COLAB_SCRIPT, COLAB_REQUIREMENTS, ASS_MODULE, LYRICS_MODULE)):
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
    _run([*colab, "upload", "--session", session, str(local_path), str(remote_path)])


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
            error = f"exit code {result.returncode}"
        except (OSError, subprocess.SubprocessError) as failure:
            error = str(failure)
    raise RuntimeError(f"Could not download {remote} after 3 attempts: {error}")


def _stop_session(colab: list[str], session: str) -> bool:
    try:
        result = _run([*colab, "stop", "--session", session], check=False, timeout=60)
        if result.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError) as error:
        LOGGER.error("Could not stop session %s: %s", session, error)
    LOGGER.error("Session %s may still be running; stop it manually", session)
    return False


def _run(
    command: list[str], *, check: bool = True, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    LOGGER.info("Running %s", " ".join(command))
    return subprocess.run(command, check=check, text=True, timeout=timeout)


if __name__ == "__main__":
    sys.exit(main())

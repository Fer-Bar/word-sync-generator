import argparse
import json
import logging
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
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
COLAB_SCRIPT = PROJECT_ROOT / "colab" / "karaoke_job.py"
ASS_MODULE = PROJECT_ROOT / "src" / "karaoke_app" / "ass.py"
LYRICS_MODULE = PROJECT_ROOT / "src" / "karaoke_app" / "lyrics_file.py"
COLAB_REQUIREMENTS = PROJECT_ROOT / "colab" / "requirements.txt"
DEFAULT_COOKIES = PROJECT_ROOT / "cookies.txt"
REMOTE_JOB = Path("/content/karaoke_job.json")
REMOTE_ARCHIVE = Path("/content/karaoke_result.zip")
REMOTE_STATUS = Path("/content/karaoke_status.json")
REMOTE_HF_TOKEN = Path("/content/.hf_token")
REMOTE_LYRICS_MODULE = Path("/content/karaoke_lyrics_file.py")
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
    parser.add_argument("--no-lrclib", action="store_true", help="Skip LRCLIB and transcribe with Faster Whisper")
    parser.add_argument("--whisper-model", default="large-v3", help="Faster Whisper model")
    parser.add_argument("--demucs-model", default="htdemucs_ft", help="Demucs separation model")
    parser.add_argument("--background-image", type=Path, help="Local image used as the video background")
    parser.add_argument("--background-color", default="#0B1020", help="Solid RGB background color")
    parser.add_argument("--resolution", choices=("1080p", "720p"), default="1080p")
    parser.add_argument("--cookies", type=Path, default=DEFAULT_COOKIES, help="Netscape cookies file for yt-dlp")
    parser.add_argument("--no-cookies", action="store_true", help="Do not upload or use a cookies file")
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
    parser.add_argument("--mode", choices=("both", "karaoke", "lyrics"), default="both")
    parser.add_argument("--gpu", choices=("T4", "L4", "G4", "A100", "H100"), default="T4")
    parser.add_argument("--auth", choices=("oauth2", "adc"), default="oauth2")
    parser.add_argument("--timeout", type=int, default=14_400)
    return parser


def main() -> int:
    """Run preparation or final render orchestration."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        if sys.argv[1:2] == ["render"]:
            args = build_render_parser().parse_args(sys.argv[2:])
            render_colab(args)
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


def run_job(args: argparse.Namespace) -> Path:
    """Provision Colab, execute the media pipeline, and download its artifacts."""
    _validate_installation()
    source_kind, source_value = _resolve_source(args.source)
    background_color = _normalize_color(args.background_color)
    background_image = args.background_image.resolve() if args.background_image else None
    if background_image and not background_image.is_file():
        raise ValueError(f"Background image not found: {background_image}")

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

    with tempfile.TemporaryDirectory(prefix="karaoke-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        job_path = temporary_path / "job.json"
        archive_path = temporary_path / "result.zip"
        status_path = temporary_path / "status.json"
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
            },
            "language": args.language,
            "lyrics": {
                "title": args.title,
                "artist": args.artist,
                "album": args.album,
                "lrclib_id": args.lrclib_id,
                "disable_lrclib": args.no_lrclib,
            },
            "whisper_model": args.whisper_model,
            "demucs_model": args.demucs_model,
            "video": {"width": width, "height": height, "fps": 24},
            "archive_path": str(REMOTE_ARCHIVE),
        }
        job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
        if hf_token:
            hf_token_path.write_text(hf_token, encoding="utf-8")
            hf_token_path.chmod(0o600)

        colab = ["colab", f"--auth={args.auth}"]
        try:
            _run([*colab, "new", "--session", session, "--gpu", args.gpu])
            session_created = True
            if source_kind == "file":
                _upload(colab, session, Path(source_value), Path(remote_source))
            if background_image and remote_background:
                _upload(colab, session, background_image, Path(remote_background))
            if cookies and remote_cookies:
                _upload(colab, session, cookies, Path(remote_cookies))
            if hf_token:
                _upload(colab, session, hf_token_path, REMOTE_HF_TOKEN)
            _upload(colab, session, job_path, REMOTE_JOB)
            _upload(colab, session, LYRICS_MODULE, REMOTE_LYRICS_MODULE)

            _run([*colab, "install", "--session", session, "--requirement", str(COLAB_REQUIREMENTS)])
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
            status_download = _run(
                [*colab, "download", "--session", session, str(REMOTE_STATUS), str(status_path)], check=False
            )
            if status_download.returncode != 0:
                raise RuntimeError("Remote pipeline ended without reporting its status")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("status") != "completed":
                raise RuntimeError(f"Remote pipeline failed: {status.get('error', 'unknown error')}")
            _run([*colab, "download", "--session", session, str(REMOTE_ARCHIVE), str(archive_path)])
            _extract_archive(archive_path, output_dir)
        finally:
            if session_created:
                _run([*colab, "stop", "--session", session], check=False)

    LOGGER.info("Artifacts saved to %s", output_dir)
    LOGGER.info("Correct %s in LyricsEditor, replace it in this folder, then run:", "lyrics.lyricsfile.yaml")
    LOGGER.info("uv run karaoke render %s", output_dir)
    return output_dir


def render_colab(args: argparse.Namespace) -> Path:
    """Validate lyrics locally and run only FFmpeg rendering on Colab."""
    from karaoke_app.ass import generate_ass
    from karaoke_app.job_document import load_job_document, resolve_job_asset
    from karaoke_app.lyrics_file import load_lyrics_file, lyrics_to_transcript

    _validate_installation()
    root = args.job_dir.expanduser().resolve()
    document = load_job_document(root)
    lyrics_path = resolve_job_asset(root, document["media"]["lyrics"], "lyrics")
    lyrics = load_lyrics_file(lyrics_path, require_words=True)
    transcript = lyrics_to_transcript(lyrics)
    modes = ("karaoke", "lyrics") if args.mode == "both" else (args.mode,)
    ass_by_mode = {
        mode: generate_ass(transcript, document["video"], scroll_long_lines=mode == "karaoke") for mode in modes
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
        _create_render_bundle(root, document, args.mode, ass_by_mode, bundle_path)
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "operation": "render",
                    "mode": args.mode,
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
        finally:
            if session_created:
                _run([*colab, "stop", "--session", session], check=False)

    LOGGER.info("Rendered artifacts saved to %s", output_dir)
    return output_dir


def _create_render_bundle(
    job_dir: Path,
    document: dict[str, object],
    mode: str,
    ass_by_mode: dict[str, str],
    destination: Path,
) -> None:
    from karaoke_app.job_document import resolve_job_asset

    media = document["media"]
    if not isinstance(media, dict):
        raise ValueError("Invalid job media configuration")
    modes = ("karaoke", "lyrics") if mode == "both" else (mode,)
    audio_keys = {"karaoke": "instrumental_audio", "lyrics": "original_audio"}
    required = {str(media[audio_keys[item]]) for item in modes}
    background = document["background"]
    if isinstance(background, dict) and background.get("kind") == "image":
        required.add(str(background["path"]))
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("job.json", json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        for item in modes:
            archive.writestr(f"{item}.ass", ass_by_mode[item])
        for relative_path in sorted(required):
            path = resolve_job_asset(job_dir, relative_path, relative_path)
            archive.write(path, relative_path)


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
                    "Invalid YouTube URL: unexpected backslash. "
                    "Use https://www.youtube.com/watch?v=VIDEO_ID"
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
    if not COLOR_PATTERN.fullmatch(value):
        raise ValueError("Background color must use the #RRGGBB format")
    return f"#{value.lstrip('#').upper()}"


def _load_hf_token() -> str | None:
    token = os.environ.get("HF_TOKEN") or dotenv_values(PROJECT_ROOT / ".env").get("HF_TOKEN")
    return token.strip() if token and token.strip() else None


def _upload(colab: list[str], session: str, local_path: Path, remote_path: Path) -> None:
    _run([*colab, "upload", "--session", session, str(local_path), str(remote_path)])


def _extract_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination_root):
                raise ValueError(f"Unsafe archive member: {member.filename}")
        archive.extractall(destination)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    LOGGER.info("Running %s", " ".join(command))
    return subprocess.run(command, check=check, text=True)


if __name__ == "__main__":
    raise SystemExit(main())

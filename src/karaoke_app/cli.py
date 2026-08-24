import argparse
import json
import logging
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
COLAB_SCRIPT = PROJECT_ROOT / "colab" / "karaoke_job.py"
COLAB_REQUIREMENTS = PROJECT_ROOT / "colab" / "requirements.txt"
DEFAULT_COOKIES = PROJECT_ROOT / "cookies.txt"
REMOTE_JOB = Path("/content/karaoke_job.json")
REMOTE_ARCHIVE = Path("/content/karaoke_result.zip")
REMOTE_STATUS = Path("/content/karaoke_status.json")
COLOR_PATTERN = re.compile(r"^#?[0-9a-fA-F]{6}$")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Generate karaoke videos on a Google Colab GPU runtime.")
    parser.add_argument("source", help="YouTube URL or local audio/video file")
    parser.add_argument("--language", default="en", help="Whisper language code")
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


def main() -> int:
    """Run the local Colab orchestration CLI."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()

    try:
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
            "whisper_model": args.whisper_model,
            "demucs_model": args.demucs_model,
            "video": {"width": width, "height": height, "fps": 24},
            "archive_path": str(REMOTE_ARCHIVE),
        }
        job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")

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
            _upload(colab, session, job_path, REMOTE_JOB)

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
    return output_dir


def _validate_installation() -> None:
    if not shutil.which("colab"):
        raise OSError("The 'colab' executable is not available. Run 'uv sync --dev' to install project dependencies.")
    if not COLAB_SCRIPT.is_file() or not COLAB_REQUIREMENTS.is_file():
        raise OSError("Colab pipeline files are missing from the project")


def _resolve_source(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "url", value
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Source file not found: {path}")
    return "file", str(path)


def _normalize_color(value: str) -> str:
    if not COLOR_PATTERN.fullmatch(value):
        raise ValueError("Background color must use the #RRGGBB format")
    return f"#{value.lstrip('#').upper()}"


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

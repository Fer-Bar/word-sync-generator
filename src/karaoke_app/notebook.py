"""Run the shared preparation pipeline inside an existing notebook GPU runtime."""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from karaoke_app.resources import PACKAGE_ROOT, runtime_resource


@dataclass(frozen=True)
class PreparedProject:
    """Durable outputs and diagnostics for one isolated preparation attempt."""

    directory: Path
    archive: Path
    runtime: Path


def runtime_report() -> dict[str, Any]:
    """Inspect prerequisites without installing packages or starting inference."""
    modules = ("demucs", "faster_whisper", "ctc_forced_aligner", "torch")
    return {
        "python": sys.version.split()[0],
        "python_supported": sys.version_info >= (3, 12),
        "commands": {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "nvidia-smi")},
        "modules": {name: importlib.util.find_spec(name) is not None for name in modules},
        "requirements": str(runtime_resource("requirements.txt")),
    }


def preparation_config(
    source: Path,
    runtime: Path,
    *,
    title: str | None = None,
    artist: str | None = None,
    language: str = "en",
    lyrics_text: Path | None = None,
    use_lrclib: bool = True,
    whisper_model: str = "large-v3",
    demucs_model: str = "htdemucs_ft",
) -> dict[str, Any]:
    """Build a local-file preparation request without filesystem writes or sessions."""
    from karaoke_app.visual_config import preparation_visuals

    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Upload a local audio/video file first: {source}")
    if lyrics_text is not None:
        lyrics_text = Path(lyrics_text).expanduser().resolve()
        if not lyrics_text.is_file():
            raise FileNotFoundError(f"Lyrics reference not found: {lyrics_text}")
    if not language.strip():
        raise ValueError("Language must not be empty")
    runtime = runtime.expanduser().resolve()
    video = {"width": 1280, "height": 720, "fps": 24}
    return {
        "schema_version": 1,
        "operation": "prepare",
        "job_id": runtime.name,
        "source_bundle": str(runtime / "source.zip"),
        "source": {"kind": "file", "value": str(source), "name": source.stem, "metadata": None},
        "cookies_path": None,
        "background": {"kind": "solid", "value": "#0B1020", "overlay_opacity": 0},
        "watermark": {"enabled": False},
        "language": language,
        "lyrics": {
            "title": title, "artist": artist, "album": None, "lrclib_id": None,
            "disable_lrclib": not use_lrclib, "text_path": str(lyrics_text) if lyrics_text else None,
            "genius_url": None,
        },
        "whisper_model": whisper_model,
        "demucs_model": demucs_model,
        "video": video,
        "archive_path": str(runtime / "prepared.zip"),
        **preparation_visuals(video, SimpleNamespace()),
    }


def _write_source_bundle(destination: Path) -> None:
    resources = {
        "karaoke_pipeline.py": runtime_resource("karaoke_job.py"),
        "karaoke_ass.py": PACKAGE_ROOT / "ass.py",
        "karaoke_lyrics_file.py": PACKAGE_ROOT / "lyrics_file.py",
        "karaoke_lyric_references.py": PACKAGE_ROOT / "lyric_references.py",
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in resources.items():
            archive.write(path, name)


def _extract_project(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination.resolve()) or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Unsafe project archive member: {member.filename}")
        archive.extractall(destination)


def _run_preparation(config_path: Path, environment: dict[str, str]) -> None:
    command = [sys.executable, "-u", str(runtime_resource("karaoke_launch.py")), str(config_path)]
    with subprocess.Popen(
        command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    ) as process:
        try:
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
            if process.wait():
                raise subprocess.CalledProcessError(process.returncode, command)
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise


def prepare_audio(
    source: Path,
    *,
    output_dir: Path,
    title: str | None = None,
    artist: str | None = None,
    language: str = "en",
    lyrics_text: Path | None = None,
    use_lrclib: bool = True,
    whisper_model: str = "large-v3",
    demucs_model: str = "htdemucs_ft",
) -> PreparedProject:
    """Prepare local audio on this runtime, preserving failed attempts for recovery.

    This does not create or stop hosted sessions, install dependencies, render videos,
    or upload inputs. Models and optional lyrics references still require Internet.
    """
    job_id = f"karaoke-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    root = Path(output_dir).expanduser().resolve()
    runtime = root / ".runs" / job_id
    config = preparation_config(
        source, runtime, title=title, artist=artist, language=language, lyrics_text=lyrics_text,
        use_lrclib=use_lrclib, whisper_model=whisper_model, demucs_model=demucs_model,
    )
    runtime.mkdir(parents=True, mode=0o700)
    config_path = runtime / "karaoke_job.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    _write_source_bundle(runtime / "source.zip")
    environment = os.environ.copy()
    environment["KARAOKE_RUNTIME_DIR"] = str(runtime)
    try:
        _run_preparation(config_path, environment)
        status = json.loads((runtime / "karaoke_status.json").read_text(encoding="utf-8"))
        if status.get("status") != "completed":
            raise RuntimeError(status.get("error_summary") or status.get("error") or "Incomplete preparation")
        archive = Path(config["archive_path"])
        destination = root / job_id
        destination.mkdir()
        _extract_project(archive, destination)
        downloadable = root / f"{job_id}.zip"
        shutil.move(archive, downloadable)
        return PreparedProject(destination, downloadable, runtime)
    except Exception as error:
        raise RuntimeError(f"Preparation failed; retained diagnostics and checkpoints in {runtime}: {error}") from error

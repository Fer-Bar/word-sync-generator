"""Prepare and render projects inside an existing notebook GPU runtime."""

import importlib.util
import json
import os
import shutil
import signal
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

from karaoke_app.resources import runtime_resource


@dataclass(frozen=True)
class PreparedProject:
    """Durable outputs and diagnostics for one isolated preparation attempt."""

    directory: Path
    archive: Path
    runtime: Path


@dataclass(frozen=True)
class RenderedProject:
    """Downloadable outputs from one isolated render, preserving previous attempts."""

    directory: Path
    archive: Path
    runtime: Path
    videos: tuple[Path, ...]


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
        "source": {"kind": "file", "value": str(source), "name": source.stem, "metadata": None},
        "cookies_path": None,
        "background": {"kind": "solid", "value": "#0B1020", "overlay_opacity": 0},
        "watermark": {"enabled": False},
        "language": language,
        "lyrics": {
            "title": title, "artist": artist, "album": None, "lrclib_id": None,
            # The CLI flag disables all references; the notebook toggle only controls online lookup.
            "disable_lrclib": not use_lrclib and lyrics_text is None,
            "text_path": str(lyrics_text) if lyrics_text else None,
            "genius_url": None,
        },
        "whisper_model": whisper_model,
        "demucs_model": demucs_model,
        "video": video,
        "archive_path": str(runtime / "prepared.zip"),
        **preparation_visuals(video, SimpleNamespace()),
    }


def _extract_project(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination.resolve()) or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Unsafe project archive member: {member.filename}")
        archive.extractall(destination)


def _run_preparation(config_path: Path, environment: dict[str, str]) -> None:
    """Run the shared launcher, which dispatches preparation and rendering requests."""
    environment = {**environment, "KARAOKE_RUNTIME_LOG_LEVEL": "INFO"}
    command = [sys.executable, "-u", str(runtime_resource("karaoke_launch.py")), str(config_path)]
    with subprocess.Popen(
        command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, start_new_session=os.name == "posix",
    ) as process:
        try:
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
            if process.wait():
                raise subprocess.CalledProcessError(process.returncode, command)
        except BaseException:
            if process.poll() is None:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
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


def render_project(
    job_dir: Path, *, options: dict[str, Any] | None = None,
) -> RenderedProject:
    """Render reviewed lyrics on this runtime without provisioning another Colab session.

    Options follow the shared project configuration service. Saved settings and earlier
    renders are preserved; failed attempts retain diagnostics under the project's .runs.
    """
    from karaoke_app.rendering import create_render_bundle, prepare_render, render_subtitles

    request = prepare_render(Path(job_dir), options or {})
    subtitles = render_subtitles(request)
    render_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{request.mode}-{uuid.uuid4().hex[:12]}"
    runtime = request.root / ".runs" / render_id
    runtime.mkdir(parents=True, mode=0o700)
    archive = runtime / "rendered.zip"
    config = {
        "schema_version": 1, "operation": "render", "mode": request.mode,
        "theme": request.theme, "archive_path": str(archive),
    }
    config_path = runtime / "karaoke_job.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    environment = os.environ.copy()
    environment["KARAOKE_RUNTIME_DIR"] = str(runtime)
    try:
        create_render_bundle(
            request.root, request.document, request.mode, subtitles.ass_by_mode,
            runtime / "karaoke_render_job.zip", transcript=subtitles.transcript, srt_content=subtitles.srt,
        )
        _run_preparation(config_path, environment)
        status = json.loads((runtime / "karaoke_status.json").read_text(encoding="utf-8"))
        if status.get("status") != "completed":
            raise RuntimeError(status.get("error_summary") or status.get("error") or "Incomplete render")
        destination = request.root / "renders" / render_id
        destination.mkdir(parents=True)
        _extract_project(archive, destination)
        videos = tuple(sorted(destination.glob("*.mp4")))
        if not videos:
            raise RuntimeError("Render completed without producing a video")
        downloadable = destination.with_suffix(".zip")
        shutil.move(archive, downloadable)
        return RenderedProject(destination, downloadable, runtime, videos)
    except Exception as error:
        raise RuntimeError(f"Render failed; retained diagnostics in {runtime}: {error}") from error

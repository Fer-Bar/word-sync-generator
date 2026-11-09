"""Exercise the public CLI through real subprocesses, project files and a PTY."""

import json
import os
import pty
import re
import select
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

from karaoke_app.job_document import STATE_FILENAME, load_job_document
from karaoke_app.visual_config import save_configuration

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    for name in ("original.wav", "instrumental.wav", "vocals.wav"):
        with wave.open(str(tmp_path / name), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\x00\x00" * 8000)
    (tmp_path / "lyrics.yaml").write_text(json.dumps({
        "version": "1.0", "metadata": {"title": "Test song", "duration_ms": 1000},
        "lines": [{"text": "Hello", "start_ms": 0, "end_ms": 900,
                   "words": [{"text": "Hello", "start_ms": 0, "end_ms": 900}]}],
    }))
    save_configuration(tmp_path, {
        "schema_version": 2, "title": "Test song", "source": {"artist": "Artist"},
        "media": {"original_audio": "original.wav", "instrumental_audio": "instrumental.wav",
                  "vocals_audio": "vocals.wav", "lyrics": "lyrics.yaml"},
        "video": {"width": 1920, "height": 1080, "fps": 24},
        "background": {"kind": "solid", "color": "#000000"}, "watermark": {"enabled": False},
    })
    return tmp_path


def environment():
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"), "TERM": "xterm", "COLUMNS": "110"}


def run_cli(*arguments):
    return subprocess.run([sys.executable, "-m", "karaoke_app.cli", *map(str, arguments)],
                          capture_output=True, text=True, timeout=20, env=environment())


def run_terminal(project, answers):
    master, slave = pty.openpty()
    process = subprocess.Popen([sys.executable, "-m", "karaoke_app.cli", "configure", str(project)],
                               stdin=slave, stdout=slave, stderr=slave, env=environment())
    os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + 20
    try:
        os.write(master, answers.encode())
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            if process.poll() is not None and not ready:
                break
        return process.wait(timeout=2), re.sub(r"\[[0-9;]*m", "", output.decode(errors="replace"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)


def snapshot(project):
    return {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob("*") if p.is_file()}


def test_configure_status_and_validate_round_trip(project):
    result = run_cli("configure", project, "--preset", "cosmic", "--title", "New title", "--artist", "New artist",
                     "--resolution", "720p", "--fps", "30", "--mode", "lyrics",
                     "--no-intro", "--font-size", "64", "--lyrics-active-color", "#ABCDEF", "--thumbnail-time", "2")
    assert result.returncode == 0, result.stderr
    document = load_job_document(project)
    assert document["title"] == "New title"
    assert document["intro"]["artist"] == "New artist"
    assert document["background"]["appearance"] == "cosmic"
    assert document["style"]["lyrics_effect"] == "word-synced"
    assert document["video"] == {"width": 1280, "height": 720, "fps": 30}
    assert document["render"] == {"mode": "lyrics"}
    assert document["intro"]["enabled"] is False
    assert document["style"]["font_size"] == 64
    assert document["style"]["lyrics_colors"]["active"] == "#ABCDEF"
    assert document["thumbnail"]["time"] == 2
    assert not (project / "job.json").exists()
    before = snapshot(project)
    status = run_cli("status", project)
    assert status.returncode == 0, status.stderr
    assert "New title" in status.stdout and "Video exports: 0" in status.stdout
    validate = run_cli("validate", project)
    assert validate.returncode == 0, validate.stderr
    assert "Colab not started" in validate.stderr
    assert snapshot(project) == before


def test_invalid_config_preserves_all_files_and_mode_validation_is_selective(project):
    before = snapshot(project)
    result = run_cli("configure", project, "--fps", "0")
    assert result.returncode == 1 and "video.fps" in result.stderr
    assert snapshot(project) == before
    (project / "instrumental.wav").unlink()
    assert run_cli("validate", project, "--mode", "lyrics").returncode == 0
    failed = run_cli("validate", project, "--mode", "karaoke")
    assert failed.returncode == 1 and "karaoke audio" in failed.stderr
    (project / "lyrics.yaml").write_text("not: valid lyrics")
    assert run_cli("validate", project, "--mode", "lyrics").returncode == 1


def test_terminal_edit_validation_summary_and_save(project):
    code, output = run_terminal(project, "6\n2\ninvalid\n0\n30\n3\n7\n8\ny\n")
    assert code == 0, output
    assert "Enter a number from 1 to 120" in output
    document = load_job_document(project)
    assert document["video"] == {"width": 1280, "height": 720, "fps": 30}
    assert document["render"]["mode"] == "lyrics"


def test_terminal_revisit_section_cancel_and_noninteractive_error(project):
    before = snapshot(project)
    code, output = run_terminal(project, "1\n2\n2\n2\n\n\n\n7\n0\n")
    assert code == 0 and "Configuration unchanged" in output, output
    assert snapshot(project) == before
    result = run_cli("configure", project)
    assert result.returncode == 1 and "explicit flags" in result.stderr
    assert snapshot(project) == before


def test_preset_explicit_background_override_and_concurrent_edit_guard(project):
    result = run_cli("configure", project, "--preset", "fluid", "--background-color", "#123456")
    assert result.returncode == 0, result.stderr
    saved = load_job_document(project)
    assert saved["background"] == {"kind": "solid", "color": "#123456"}
    changed = json.loads((project / STATE_FILENAME).read_text())
    changed["title"] = "Changed elsewhere"
    save_configuration(project, changed)
    with pytest.raises(ValueError, match="Project changed"):
        save_configuration(project, saved, expected=saved)
    assert load_job_document(project)["title"] == "Changed elsewhere"


def test_source_preset_resolves_before_remote_work():
    from karaoke_app.cli import build_parser
    from karaoke_app.visual_config import preparation_visuals

    args = build_parser().parse_args(["song.wav", "--preset", "classic"])
    visuals = preparation_visuals({"width": 1280, "height": 720, "fps": 24}, args)
    assert visuals["render_style"]["lyrics_effect"] == "classic"
    assert visuals["render_background"] == {"kind": "solid", "color": "#0B1020"}


def test_legacy_root_document_is_not_loaded_or_changed(tmp_path):
    old = tmp_path / "job.json"
    old.write_text('{"schema_version": 1}')
    before = snapshot(tmp_path)
    result = run_cli("status", tmp_path)
    assert result.returncode == 1 and "Prepare it with karaoke source" in " ".join(result.stderr.split())
    assert snapshot(tmp_path) == before


def test_terminal_input_interruption_preserves_project(project):
    before = snapshot(project)
    code, output = run_terminal(project, "1\n2\n\x04")
    assert code == 1, output
    assert snapshot(project) == before

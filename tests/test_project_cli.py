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


def run_cli(*arguments, cwd=None):
    return subprocess.run([sys.executable, "-m", "karaoke_app.cli", *map(str, arguments)],
                          capture_output=True, text=True, timeout=20, env=environment(), cwd=cwd)


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
    invocation = project / "invocation"
    invocation.mkdir()
    before = snapshot(project)
    logs_before = snapshot(ROOT / ".karaoke/logs")
    invocation_before = snapshot(invocation)
    status = run_cli("--verbose", "status", project, cwd=invocation)
    assert status.returncode == 0, status.stderr
    assert "New title" in status.stdout and "Video exports: 0" in status.stdout
    validate = run_cli("validate", project, "--verbose", cwd=invocation)
    assert validate.returncode == 0, validate.stderr
    assert "Colab not started" in validate.stderr
    assert snapshot(project) == before
    assert snapshot(ROOT / ".karaoke/logs") == logs_before
    assert snapshot(invocation) == invocation_before


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


def test_classic_colors_can_be_set_without_an_existing_palette(project):
    assert load_job_document(project)["style"].get("lyrics_colors") is None
    result = run_cli("configure", project, "--lyrics-active-color", "#22CCFF", "--lyrics-inactive-color", "#334455")
    assert result.returncode == 0, result.stderr
    document = load_job_document(project)
    assert document["style"]["lyrics_colors"] == {"active": "#22CCFF", "inactive": "#334455"}
    assert run_cli("validate", project).returncode == 0
    from karaoke_app.ass import generate_ass
    from karaoke_app.lyrics_file import load_lyrics_file, lyrics_to_transcript
    from karaoke_app.style import StyleConfig, hex_to_ass_color

    transcript = lyrics_to_transcript(load_lyrics_file(project / "lyrics.yaml"))
    for mode in ("karaoke", "lyrics"):
        subtitles = generate_ass(
            transcript, document["video"], style=StyleConfig.from_dict(document["style"]), mode=mode)
        assert hex_to_ass_color("#22CCFF") in subtitles
        assert hex_to_ass_color("#334455") in subtitles


@pytest.fixture
def video_background(project):
    import imageio_ffmpeg

    video = project / "background.mp4"
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=200x100:r=8:d=2",
        "-vf", "drawbox=x=150:y=0:w=50:h=100:color=blue:t=fill", "-pix_fmt", "yuv420p", str(video),
    ], check=True, capture_output=True, timeout=20)
    return video


def test_cli_video_background_and_artwork_settings_reach_real_graphics(project, video_background):
    import zipfile

    from PIL import Image

    from karaoke_app.ass import generate_ass
    from karaoke_app.cli import _create_render_bundle
    from karaoke_app.lyrics_file import load_lyrics_file, lyrics_to_transcript
    from karaoke_app.render_graphics import background_frame, generate_render_graphics
    from karaoke_app.style import StyleConfig

    result = run_cli("configure", project, "--background-video", video_background,
                     "--background-crop-right", "0.25", "--background-overlay-opacity", "0.5",
                     "--intro", "--intro-start", "0.1", "--intro-end", "0.6",
                     "--thumbnail-time", "0.7", "--thumbnail-align", "end")
    assert result.returncode == 0, result.stderr
    document = load_job_document(project)
    assert run_cli("validate", project).returncode == 0
    # Crop removes the blue strip, then darkening halves the decoded red pixels.
    frame = background_frame(project, document, time=0.7)
    for point in ((0, 0), (frame.width // 2, frame.height // 2), (frame.width - 1, frame.height - 1)):
        red, green, blue = frame.getpixel(point)
        assert 115 <= red <= 135 and green < 10 and blue < 10
    lyrics = json.loads((project / "lyrics.yaml").read_text())
    lyrics["metadata"]["duration_ms"] = 2000
    lyrics["lines"][0].update(start_ms=1500, end_ms=1900)
    lyrics["lines"][0]["words"][0].update(start_ms=1500, end_ms=1900)
    (project / "lyrics.yaml").write_text(json.dumps(lyrics))
    with wave.open(str(project / "original.wav"), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * 16000)
    transcript = lyrics_to_transcript(load_lyrics_file(project / "lyrics.yaml"))
    graphics = project / "graphics-check"
    timing = generate_render_graphics(project, document, ("lyrics",), graphics, transcript)
    assert timing["start"] == pytest.approx(0.1)
    assert timing["end"] == pytest.approx(0.6)
    assert timing["duration"] == pytest.approx(0.5)
    with Image.open(graphics / "thumbnails/thumbnail_lyrics.png") as thumbnail:
        # Independent thumbnail alignment changes the composition, not the video background.
        assert thumbnail.size == (1280, 720)
        assert thumbnail.convert("RGB").tobytes() != frame.resize(thumbnail.size).tobytes()
        import numpy as np

        pixels = np.asarray(thumbnail.convert("RGB"))
        _, ink_columns = np.where((pixels[:, :, 1] > 180) & (pixels[:, :, 2] > 180))
        assert (ink_columns.min() + ink_columns.max()) / 2 > thumbnail.width / 2
    bundle = project / "render.zip"
    ass = generate_ass(transcript, document["video"], style=StyleConfig.from_dict(document["style"]), mode="lyrics")
    _create_render_bundle(project, document, "lyrics", {"lyrics": ass}, bundle, transcript=transcript)
    with zipfile.ZipFile(bundle) as archive:
        assert archive.read("background.mp4") == video_background.read_bytes()
        packed = json.loads(archive.read(STATE_FILENAME))
        assert packed["background"] == document["background"]
        assert packed["intro"]["end"] == pytest.approx(0.6)
    # A duration replaces the old absolute end, and separate thumbnail alignment survives.
    changed = run_cli("configure", project, "--intro-duration", "0.3")
    assert changed.returncode == 0, changed.stderr
    saved = load_job_document(project)
    assert "end" not in saved["intro"]
    assert saved["thumbnail"]["align"] == "end"
    # An explicit end is not silently capped by the default five-second duration.
    assert run_cli("configure", project, "--intro-start", "0.5", "--intro-end", "6").returncode == 0
    lyrics["metadata"]["duration_ms"] = 8000
    lyrics["lines"][0].update(start_ms=7500, end_ms=7900)
    lyrics["lines"][0]["words"][0].update(start_ms=7500, end_ms=7900)
    (project / "lyrics.yaml").write_text(json.dumps(lyrics))
    with wave.open(str(project / "original.wav"), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * 64000)
    transcript = lyrics_to_transcript(load_lyrics_file(project / "lyrics.yaml"))
    timing = generate_render_graphics(project, load_job_document(project), ("lyrics",), graphics, transcript)
    assert timing["start"] == pytest.approx(0.5)
    assert timing["end"] == pytest.approx(6)
    assert run_cli("configure", project, "--intro-duration", "6.2").returncode == 0
    timing = generate_render_graphics(project, load_job_document(project), ("lyrics",), graphics, transcript)
    assert timing["end"] == pytest.approx(6.7)



def test_invalid_video_and_artwork_options_preserve_the_project(project, video_background):
    original = snapshot(project)
    cases = [
        ("--background-video", video_background, "--background-image", video_background),
        ("--background-video", video_background, "--background-crop-right", "0.51"),
        ("--background-video", video_background, "--background-overlay-opacity", "nan"),
        ("--background-video", video_background, "--thumbnail-time", "2"),
        ("--intro-start", "1", "--intro-end", "0.5"),
        ("--intro-duration", "1", "--intro-end", "2"),
    ]
    for arguments in cases:
        result = run_cli("configure", project, *arguments)
        assert result.returncode == 1, (arguments, result.stderr)
        assert snapshot(project) == original
    video_background.write_bytes(b"not video")
    result = run_cli("configure", project, "--background-video", video_background)
    assert result.returncode == 1 and "decodable video frame" in " ".join(result.stderr.split())
    assert load_job_document(project)["background"]["kind"] == "solid"


def test_terminal_video_section_accepts_a_relative_asset_and_saves(project, video_background):
    # Background section: video, relative path, dimming, crop, then save.
    code, output = run_terminal(project, "3\n5\nbackground.mp4\n0.2\n0.25\n8\ny\n")
    assert code == 0, output
    assert load_job_document(project)["background"] == {
        "kind": "video", "path": "background.mp4", "overlay_opacity": 0.2, "crop_right": 0.25,
    }

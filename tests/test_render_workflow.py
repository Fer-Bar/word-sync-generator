"""Render real project assets, then decode the artifacts instead of asserting calls."""

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest

from colab import karaoke_job as job
from karaoke_app import lyrics_plus
from karaoke_app.ass import generate_ass
from karaoke_app.cli import _create_render_bundle
from karaoke_app.job_document import load_job_document
from karaoke_app.lyrics_file import load_lyrics_file, lyrics_to_transcript
from karaoke_app.srt import generate_srt
from karaoke_app.style import StyleConfig

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@pytest.fixture
def media_tools(tmp_path, monkeypatch):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "ffmpeg").symlink_to(FFMPEG)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ.get("PATH", ""))

    def decoded_duration(path):
        # The local dependency bundles FFmpeg, not FFprobe. Decode the actual input
        # instead of returning a fabricated duration; all composition stays real.
        pcm = run_media(FFMPEG, "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                        "-ar", "16000", "-f", "s16le", "pipe:1").stdout
        return len(pcm) / (16000 * 2)

    monkeypatch.setattr(job, "_probe_duration", decoded_duration)

def run_media(*command):
    return subprocess.run(command, capture_output=True, check=True)


def decode_frame(path, instant):
    result = run_media(FFMPEG, "-v", "error", "-ss", str(instant), "-i", str(path),
                       "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(180, 320, 3)


def assert_video(path, frequency):
    frames = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgb24")
    metadata = next(frames)
    assert (metadata["size"], metadata["fps"]) == ((320, 180), 8)
    assert metadata["duration"] == pytest.approx(1, abs=.15)
    assert sum(1 for _ in frames) == 8
    # Decode every packet, not just the header or a nonempty file.
    run_media(FFMPEG, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-")
    pcm = run_media(FFMPEG, "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                    "-ar", "16000", "-f", "s16le", "pipe:1").stdout
    samples = np.frombuffer(pcm, dtype="<i2").astype(float)
    assert len(samples) >= 16000
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    peak = np.fft.rfftfreq(len(samples), 1 / 16000)[np.argmax(spectrum)]
    assert peak == pytest.approx(frequency, abs=5)


@pytest.mark.parametrize("renderer", ["ass", "browser"])
def test_project_bundle_renders_both_modes_with_the_right_audio_and_subtitles(
    prepared_project, tmp_path, monkeypatch, media_tools, renderer,
):
    document = load_job_document(prepared_project)
    if renderer == "browser":
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                message = "Install Chromium with: uv run playwright install --with-deps chromium"
                if os.environ.get("CI"):
                    pytest.fail(message)
                pytest.skip(message)
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        # A real bundled font keeps the browser path offline. Only font acquisition
        # is substituted; the archive's canonical filename is part of its protocol.
        fonts = Path(lyrics_plus.__file__).parent / "assets/fonts"
        font = tmp_path / "Switzer-Semibold.otf"
        shutil.copyfile(fonts / "Montserrat.ttf", font)
        shutil.copyfile(fonts / "Montserrat-OFL.txt", font.with_name("Switzer-FFL.txt"))
        monkeypatch.setattr(lyrics_plus, "switzer_font", lambda: font)
        document["style"].update(lyrics_effect="word-synced", font_family="Montserrat")
        # Browser binaries are a test prerequisite, not installed during rendering.
        monkeypatch.setattr(job, "_run_installer", lambda *args, **kwargs: None)
    transcript = lyrics_to_transcript(load_lyrics_file(prepared_project / "lyrics.yaml"))
    subtitles = {
        mode: generate_ass(transcript, document["video"], style=StyleConfig.from_dict(document["style"]), mode=mode)
        for mode in ("lyrics", "karaoke")
    }
    bundle, result = tmp_path / "bundle.zip", tmp_path / "result.zip"
    _create_render_bundle(prepared_project, document, "both", subtitles, bundle,
                          transcript=transcript, srt_content=generate_srt(transcript))
    monkeypatch.setattr(job, "WORK_DIR", tmp_path / "remote")
    monkeypatch.setattr(job, "RENDER_JOB_PATH", bundle)
    # Bootstrap is separate from rendering: tests never apt-install/download fonts.
    # NVENC detection, FFmpeg, archive I/O and all rendering remain real.
    monkeypatch.setattr(job, "_ensure_system_fonts", lambda: None)
    monkeypatch.setattr(job, "_ensure_bebas_font", lambda: None)
    job._render_existing_job({"mode": "both", "archive_path": str(result)})

    extracted = tmp_path / "downloaded"
    with zipfile.ZipFile(result) as archive:
        assert archive.testzip() is None
        archive.extractall(extracted)
    settings = json.loads((extracted / "render-settings.json").read_text())
    assert settings["renderer"] == ("braccato-1.6.2" if renderer == "browser" else "ass")
    for mode, frequency in (("lyrics", 440), ("karaoke", 880)):
        video = extracted / f"Song_{mode}.mp4"
        assert_video(video, frequency)
        assert np.count_nonzero(decode_frame(video, .5).max(axis=2) > 100) > 20
        assert (extracted / "subtitles" / f"Song_{mode}.ass").read_text() == subtitles[mode]
        assert "00:00:00,200 --> 00:00:00,800" in (
            extracted / "subtitles" / f"Song_{mode}.srt"
        ).read_text()
        assert "Hello world" in (extracted / "subtitles" / f"Song_{mode}.srt").read_text()


def test_render_without_subtitles_produces_plain_video(prepared_project, tmp_path, media_tools):
    output = tmp_path / "plain.mp4"
    job._render_video(prepared_project / "original.wav", output, {
        "video": {"width": 320, "height": 180, "fps": 8},
        "background": {"kind": "solid", "value": "#000000"},
    })
    assert_video(output, 440)
    assert decode_frame(output, .5).max() < 10


@pytest.mark.parametrize("exit_code", [0, 2])
def test_installer_reports_real_process_output(exit_code):
    script = f"import sys; print('installed'); print('details', file=sys.stderr); sys.exit({exit_code})"
    command = [sys.executable, "-c", script]
    if exit_code:
        with pytest.raises(RuntimeError, match="Fixture installation failed.*details"):
            job._run_installer(command, label="Fixture")
    else:
        result = job._run_installer(command, label="Fixture")
        assert result.returncode == 0
        assert result.stdout.strip() == "installed"

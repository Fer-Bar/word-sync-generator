"""Small, valid media projects shared by local workflow integration tests."""

import json
import os
import subprocess
import wave

import imageio_ffmpeg
import numpy as np
import pytest

from colab import karaoke_job as job
from karaoke_app.job_document import JOB_FILENAME
from karaoke_app.lyrics_file import dump_lyrics_file


@pytest.fixture
def prepared_project(tmp_path):
    root = tmp_path / "song"
    root.mkdir()
    # Different tones catch swapped stems in the decoded final videos.
    for name, frequency in (("original", 440), ("instrumental", 880), ("vocals", 1320)):
        samples = np.sin(2 * np.pi * frequency * np.arange(16000) / 16000)
        with wave.open(str(root / f"{name}.wav"), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes((samples * 12000).astype("<i2").tobytes())
    lyrics = {
        "version": "1.0", "metadata": {"title": "Song", "language": "en", "duration_ms": 1000},
        "lines": [{"text": "Hello world", "start_ms": 200, "end_ms": 800, "words": [
            {"text": "Hello ", "start_ms": 200, "end_ms": 500},
            {"text": "world", "start_ms": 500, "end_ms": 800},
        ]}],
    }
    (root / "lyrics.yaml").write_text(dump_lyrics_file(lyrics), encoding="utf-8")
    document = {
        "schema_version": 2, "title": "Song", "source": {"artist": "Test artist"},
        "video": {"width": 320, "height": 180, "fps": 8},
        "media": {"lyrics": "lyrics.yaml", "vocals_audio": "vocals.wav",
                  "original_audio": "original.wav", "instrumental_audio": "instrumental.wav"},
        "background": {"kind": "solid", "color": "#000000"},
        "watermark": {"enabled": False}, "intro": {"enabled": False},
        "style": {"font_size": 24, "margin_h": 20, "margin_v": 20},
    }
    state = root / JOB_FILENAME
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(document), encoding="utf-8")
    return root


@pytest.fixture
def media_tools(tmp_path, monkeypatch):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "ffmpeg").symlink_to(ffmpeg)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ.get("PATH", ""))

    def decoded_duration(path):
        # The local dependency bundles FFmpeg, not FFprobe. Decode the actual input
        # instead of returning a fabricated duration; all composition stays real.
        pcm = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                              "-ar", "16000", "-f", "s16le", "pipe:1"],
                             capture_output=True, check=True).stdout
        return len(pcm) / (16000 * 2)

    monkeypatch.setattr(job, "_probe_duration", decoded_duration)
